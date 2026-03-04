"""
抖音（中国版）下载器
使用系统浏览器（Edge/Chrome）可执行文件，启动前将系统 profile 的 cookies 同步到独立目录，
避免与正在运行的浏览器争抢文件锁。
"""

import asyncio
import re
import shutil
import time
import json
import os
import random
from pathlib import Path
from typing import AsyncGenerator, Optional
from datetime import datetime

import httpx

from src.core.models import Platform, VideoInfo, DownloadResult, DownloadProgress
from src.core.interfaces import IDownloader, IProgressCallback
from src.core.exceptions import DownloaderError, VideoNotFoundError, NetworkError
from src.config import get_settings


class DouyinDownloader(IDownloader):
    """抖音视频下载器 - 使用系统浏览器（Edge/Chrome）可执行文件"""

    # 独立 profile 目录，避免与正在运行的系统浏览器争抢文件锁
    PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\chrome-profile"))

    # 日志目录 - 保存调试信息
    LOG_DIR = Path(__file__).parent.parent.parent.parent / "logs"

    # ========== 反爬配置 ==========
    # 最大单次延迟 2.5 秒
    SCROLL_DELAY = (1.0, 2.0)       # 滚动间隔（秒）
    SCROLL_RETRY_DELAY = (5.0, 8.0)  # 无新内容时的重试等待（秒），页面加载慢时需要更久
    PAGE_LOAD_DELAY = (1.5, 2.5)    # 页面加载后等待（秒）
    VIDEO_INTERVAL = (0.8, 1.8)     # 视频之间间隔（秒）
    DOWNLOAD_INTERVAL = (0.3, 1.0)     # 下载间隔（秒）

    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    @staticmethod
    def _random_delay(delay_range: tuple) -> int:
        """生成随机延迟时间（毫秒）"""
        return int(random.uniform(delay_range[0], delay_range[1]) * 1000)

    @staticmethod
    async def _check_captcha(page) -> tuple[bool, str]:
        """
        检测页面是否出现验证码或登录弹窗

        Returns:
            (是否有验证码/登录, 类型描述)
        """
        # 按优先级检测
        checks = [
            # 登录弹窗 - 优先检测
            ('div[class*="login-panel"]', '登录弹窗'),
            ('div[class*="loginContainer"]', '登录弹窗'),
            ('div[class*="login-guide"]', '登录弹窗'),
            ('div.login-mask', '登录弹窗'),
            # 验证码
            ('div.captcha_verify_container', '滑块验证码'),
            ('div[class*="captcha-verify"]', '滑块验证码'),
            ('div#captcha_container', '验证码'),
            ('div.verify-captcha-container', '图片验证码'),
            ('div[class*="secsdk-captcha"]', '安全验证码'),
            ('div[class*="captcha"]', '验证码'),
            ('iframe[src*="captcha"]', '验证码'),
            # 海外访问提示
            ('div[class*="region"]', '地区限制提示'),
        ]
        for selector, block_type in checks:
            try:
                elem = await page.query_selector(selector)
                if elem and await elem.is_visible():
                    return True, block_type
            except Exception:
                pass
        return False, ""

    async def _wait_for_auth_resolved(self, page, max_wait: int = 120) -> bool:
        """
        等待用户完成验证码/登录，最多等待 max_wait 秒
        每次检测到阻断会记录日志
        """
        start = time.time()
        last_type = ""
        while time.time() - start < max_wait:
            has_block, block_type = await self._check_captcha(page)
            if not has_block:
                return True
            # 类型变化时记录日志
            if block_type != last_type:
                print(f"[抖音下载] ⏳ 等待用户完成: {block_type}")
                last_type = block_type
            await page.wait_for_timeout(1000)
        return False

    async def _wait_and_retry_auth(self, page, max_retries: int = 10) -> bool:
        """
        循环检测验证码/登录，直到页面正常或达到最大重试次数
        验证码和登录可能反复出现，每次检测到等待 10-12 秒后重试

        Returns:
            True 如果最终通过，False 如果超时
        """
        for attempt in range(max_retries):
            has_block, block_type = await self._check_captcha(page)

            if not has_block:
                if attempt > 0:
                    print(f"[抖音下载] ✓ 验证/登录已全部完成")
                return True

            # 检测到阻断，记录并等待用户处理
            print(f"[抖音下载] ⚠️ 检测到 {block_type}！请在浏览器中完成... (第{attempt+1}次)")

            # 等待用户完成（最多120秒）
            resolved = await self._wait_for_auth_resolved(page, 120)
            if not resolved:
                print(f"[抖音下载] ✗ 等待超时")
                return False

            print(f"[抖音下载] ✓ {block_type} 已通过")

            # 等待 10-12 秒让页面刷新，可能还有下一个验证
            wait_time = random.uniform(10, 12)
            print(f"[抖音下载] 等待页面刷新 ({wait_time:.1f}s)...")
            await page.wait_for_timeout(int(wait_time * 1000))

        return False

    async def _save_debug_info(self, page, reason: str = "unknown") -> None:
        """保存调试信息：截图 + 页面源代码"""
        timestamp = int(time.time())

        # 确保日志目录存在
        self.LOG_DIR.mkdir(parents=True, exist_ok=True)

        # 保存截图
        screenshot_path = self.LOG_DIR / f"debug_{reason}_{timestamp}.png"
        try:
            await page.screenshot(path=str(screenshot_path))
            print(f"[抖音下载] 📸 已保存截图: {screenshot_path}")
        except Exception as e:
            print(f"[抖音下载] 截图保存失败: {e}")

        # 保存页面源代码
        html_path = self.LOG_DIR / f"debug_{reason}_{timestamp}.html"
        try:
            content = await page.content()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"[抖音下载] 📄 已保存源代码: {html_path}")
        except Exception as e:
            print(f"[抖音下载] 源代码保存失败: {e}")

        # 打印页面基本信息
        try:
            title = await page.title()
            current_url = page.url
            print(f"[抖音下载] 页面标题: {title}")
            print(f"[抖音下载] 当前URL: {current_url}")
        except Exception:
            pass

    def _save_video_urls_log(self, user_url: str, video_urls: list[str]) -> Path:
        """
        保存提取的视频URL列表到调试日志文件

        Args:
            user_url: 用户主页URL
            video_urls: 提取的视频URL列表

        Returns:
            日志文件路径
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.LOG_DIR / f"video_urls_{timestamp}.txt"

        try:
            self.LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"# 抖音视频URL提取日志\n")
                f.write(f"# 时间: {datetime.now().isoformat()}\n")
                f.write(f"# 用户主页: {user_url}\n")
                f.write(f"# 视频数量: {len(video_urls)}\n")
                f.write(f"# {'='*50}\n\n")

                for i, url in enumerate(video_urls, 1):
                    f.write(f"{i:03d}. {url}\n")

            print(f"[抖音下载] 📝 已保存视频URL列表: {log_path}")
            return log_path
        except Exception as e:
            print(f"[抖音下载] ⚠️ 保存URL列表失败: {e}")
            return log_path

    def __init__(self):
        self.settings = get_settings()
        self._progress_callback: Optional[IProgressCallback] = None
        self._current_progress = DownloadProgress()
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def platform(self) -> Platform:
        return Platform.DOUYIN

    @property
    def supported_domains(self) -> list[str]:
        return [
            "douyin.com",
            "v.douyin.com",
            "iesdouyin.com",
        ]

    # 抖音有效链接正则
    VIDEO_URL_PATTERN = re.compile(r'douyin\.com/video/\d+')
    USER_URL_PATTERN = re.compile(r'douyin\.com/user/[A-Za-z0-9_-]+')
    SHORT_URL_PATTERN = re.compile(r'v\.douyin\.com/[A-Za-z0-9]+')

    @staticmethod
    def is_user_profile_url(url: str) -> bool:
        """检查是否为用户主页URL"""
        return "/user/" in url

    @classmethod
    def validate_url(cls, url: str) -> tuple[bool, str]:
        """
        验证抖音链接格式是否有效

        Returns:
            (is_valid, error_message)
        """
        # 检查是否为抖音域名
        if not any(domain in url.lower() for domain in ["douyin.com", "iesdouyin.com"]):
            return False, "不是抖音链接"

        # 检查是否为有效格式
        if cls.VIDEO_URL_PATTERN.search(url):
            return True, ""
        if cls.USER_URL_PATTERN.search(url):
            return True, ""
        if cls.SHORT_URL_PATTERN.search(url):
            return True, ""

        # 无效格式，给出提示
        return False, (
            "抖音链接格式不正确。支持的格式：\n"
            "  • 视频链接: https://www.douyin.com/video/7456789012345678901\n"
            "  • 用户主页: https://www.douyin.com/user/MS4wLjABAAAAxxxxx\n"
            "  • 短链接: https://v.douyin.com/xxxxxx\n"
            "当前链接不符合以上格式，请检查后重试。"
        )

    def supports_url(self, url: str) -> bool:
        url_lower = url.lower()
        return any(domain in url_lower for domain in self.supported_domains)

    def _extract_video_id(self, url: str) -> str:
        match = re.search(r'/video/(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'modal_id=(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/(\d{15,20})', url)
        if match:
            return match.group(1)
        return ""

    def _get_chrome_path(self) -> Optional[str]:
        """获取本地 Chrome/Edge 浏览器路径（优先 Chrome）"""
        possible_paths = [
            # Chrome 优先
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            # Edge 备用
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None

    def _get_native_user_data_dir(self) -> Optional[Path]:
        """获取系统浏览器的用户数据目录（优先 Chrome，与 _get_chrome_path 保持一致）"""
        candidates = [
            # Chrome 优先
            Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")),
            # Edge 备用
            Path(os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data")),
        ]
        for p in candidates:
            if (p / "Default").exists():
                return p
        return None

    def _is_profile_initialized(self) -> bool:
        """检查 Profile 是否已初始化（已有登录态）"""
        cookies_file = self.PROFILE_DIR / "Default" / "Network" / "Cookies"
        local_state = self.PROFILE_DIR / "Local State"
        return cookies_file.exists() and local_state.exists()

    def _sync_native_profile(self, force: bool = False) -> None:
        """
        将系统浏览器（Edge/Chrome）的配置、登录态、网站缓存同步到独立 profile 目录。

        Args:
            force: 是否强制同步（覆盖已有数据）

        注意：只在首次或强制时同步，避免覆盖已有登录状态。
        """
        # 如果已初始化且非强制，跳过同步
        if self._is_profile_initialized() and not force:
            print(f"[抖音下载] Profile 已存在，跳过同步（保留已有登录态）")
            return

        native_dir = self._get_native_user_data_dir()
        if not native_dir:
            print(f"[抖音下载] 未找到系统浏览器 Profile，将使用空白配置")
            return

        target = self.PROFILE_DIR
        print(f"[抖音下载] 首次同步，从 {native_dir} 复制登录态...")

        # 单个文件：cookie 加密密钥 + cookie 数据库 + 配置
        files = [
            "Local State",
            "Default/Network/Cookies",
            "Default/Network/Cookies-journal",
            "Default/Cookies",
            "Default/Cookies-journal",
            "Default/Preferences",
            "Default/Secure Preferences",
            "Default/Web Data",          # 自动填充、搜索引擎等配置
            "Default/Web Data-journal",
            "Default/Network/Trust Tokens",
        ]
        # 目录：登录态存储 + 网站缓存
        dirs = [
            "Default/Local Storage",
            "Default/Session Storage",
            "Default/IndexedDB",         # IndexedDB 数据（部分网站登录态存这里）
            "Default/Cache",             # HTTP 缓存
            "Default/Code Cache",        # JS/WASM 编译缓存
            "Default/Service Worker",    # Service Worker 注册及缓存
            "Default/Network",           # 网络状态（HSTS、DNS 缓存等）
        ]

        for rel in files:
            src = native_dir / rel
            dst = target / rel
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(str(src), str(dst))
                except (PermissionError, OSError):
                    pass  # 浏览器运行中可能锁定部分文件，跳过

        for rel in dirs:
            src = native_dir / rel
            dst = target / rel
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    if dst.exists():
                        shutil.rmtree(str(dst), ignore_errors=True)
                    shutil.copytree(str(src), str(dst), dirs_exist_ok=True,
                                    ignore_dangling_symlinks=True)
                except (PermissionError, OSError):
                    pass

    async def _get_video_data_playwright(self, url: str) -> dict:
        """使用系统浏览器可执行文件启动 Playwright，获取视频数据"""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise DownloaderError(url=url, message="请安装 playwright: pip install playwright")

        # 将系统浏览器的登录态同步到独立 profile（仅首次）
        self._sync_native_profile()

        video_data = {}
        chrome_path = self._get_chrome_path()
        print(f"[抖音下载] 使用浏览器: {chrome_path or 'Playwright 内置'}")

        async with async_playwright() as p:
            launch_options = {
                "user_data_dir": str(self.PROFILE_DIR),
                "headless": False,  # 使用可见浏览器，不易被检测
                "args": [
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
                "viewport": {"width": 1280, "height": 800},
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            }

            # 如果找到本地 Chrome，使用它
            if chrome_path:
                launch_options["executable_path"] = chrome_path

            print(f"[抖音下载] 正在启动浏览器...")
            context = await p.chromium.launch_persistent_context(**launch_options)
            print(f"[抖音下载] 浏览器已启动")

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 注入反检测脚本
                await page.add_init_script("""
                    // 隐藏 webdriver 标识
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    delete navigator.__proto__.webdriver;

                    // 伪造插件
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [
                            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                            { name: 'Native Client', filename: 'internal-nacl-plugin' }
                        ]
                    });

                    // 语言设置
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

                    // Chrome 对象
                    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };

                    // 隐藏自动化特征
                    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });
                    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                """)

                # 监听网络请求，捕获视频信息 API
                video_info_captured = asyncio.Event()

                async def handle_response(response):
                    nonlocal video_data
                    try:
                        resp_url = response.url
                        if "aweme/v1/web/aweme/detail" in resp_url or "/aweme/detail" in resp_url:
                            if response.status == 200:
                                try:
                                    data = await response.json()
                                    if data.get("aweme_detail"):
                                        video_data = data["aweme_detail"]
                                        video_info_captured.set()
                                except:
                                    pass
                    except:
                        pass

                page.on("response", handle_response)

                # 访问视频页面
                print(f"[抖音下载] 正在访问页面: {url}")
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                print(f"[抖音下载] 页面已加载，等待视频信息...")

                # 循环检测验证码/登录（可能反复出现）
                auth_ok = await self._wait_and_retry_auth(page, max_retries=10)
                if not auth_ok:
                    await self._save_debug_info(page, "video_auth_timeout")
                    raise DownloaderError(url=url, message="验证码/登录超时未完成")

                # 等待视频信息被捕获
                try:
                    await asyncio.wait_for(video_info_captured.wait(), timeout=20)
                    print(f"[抖音下载] 已捕获视频信息")
                except asyncio.TimeoutError:
                    print(f"[抖音下载] 等待超时，尝试从页面提取...")

                # 如果没捕获到，尝试从页面提取
                if not video_data:
                    await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))
                    video_data = await self._extract_from_page(page)
                    if video_data:
                        print(f"[抖音下载] 从页面提取到视频信息")

            finally:
                print(f"[抖音下载] 关闭浏览器...")
                await context.close()

        if not video_data:
            raise VideoNotFoundError(url, "无法获取视频信息。如果是首次使用，浏览器窗口可能需要你完成验证。")

        return video_data

    async def _extract_from_page(self, page) -> dict:
        """从页面提取视频数据"""
        # 尝试从 RENDER_DATA 提取
        render_data = await page.evaluate('''() => {
            const script = document.getElementById('RENDER_DATA');
            if (script) {
                try {
                    return decodeURIComponent(script.textContent);
                } catch {
                    return script.textContent;
                }
            }
            return null;
        }''')

        if render_data:
            try:
                data = json.loads(render_data)
                for key, value in data.items():
                    if isinstance(value, dict):
                        if "aweme" in value:
                            aweme = value.get("aweme", {})
                            if "detail" in aweme:
                                return aweme["detail"]
                        if "video" in value and "author" in value:
                            return value
            except:
                pass

        # 尝试从 __INITIAL_STATE__ 提取
        initial_state = await page.evaluate('''() => {
            if (window.__INITIAL_STATE__) {
                return JSON.stringify(window.__INITIAL_STATE__);
            }
            return null;
        }''')

        if initial_state:
            try:
                data = json.loads(initial_state)
                if "aweme" in data:
                    return data["aweme"]
            except:
                pass

        return {}

    def _extract_video_url(self, video_data: dict) -> str:
        """从视频数据中提取下载URL"""
        video = video_data.get("video", {})

        # 方法1: play_addr
        play_addr = video.get("play_addr", {})
        url_list = play_addr.get("url_list", [])
        if url_list:
            video_url = url_list[0]
            video_url = video_url.replace("playwm", "play")
            return video_url

        # 方法2: bit_rate (选择最高码率)
        bit_rate = video.get("bit_rate", [])
        if bit_rate:
            sorted_rates = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
            play_addr = sorted_rates[0].get("play_addr", {})
            url_list = play_addr.get("url_list", [])
            if url_list:
                return url_list[0]

        # 方法3: download_addr
        download_addr = video.get("download_addr", {})
        url_list = download_addr.get("url_list", [])
        if url_list:
            return url_list[0]

        raise DownloaderError(url="", message="无法获取视频下载链接")

    def _parse_video_info(self, video_data: dict, url: str) -> VideoInfo:
        """解析视频信息"""
        author_info = video_data.get("author", {})
        statistics = video_data.get("statistics", {})

        upload_date = None
        if create_time := video_data.get("create_time"):
            try:
                upload_date = datetime.fromtimestamp(create_time)
            except:
                pass

        duration = video_data.get("video", {}).get("duration", 0)
        if duration > 1000:
            duration = duration // 1000

        return VideoInfo(
            url=url,
            platform=Platform.DOUYIN,
            video_id=video_data.get("aweme_id", self._extract_video_id(url)),
            title=video_data.get("desc", "抖音视频") or "抖音视频",
            author=author_info.get("nickname"),
            duration=duration,
            thumbnail=video_data.get("video", {}).get("cover", {}).get("url_list", [None])[0],
            description=video_data.get("desc"),
            upload_date=upload_date,
            view_count=statistics.get("play_count"),
            like_count=statistics.get("digg_count"),
            available_qualities=["best"],
            raw_data=video_data,
        )

    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息"""
        # 验证链接格式
        is_valid, error_msg = self.validate_url(url)
        if not is_valid:
            raise DownloaderError(url=url, message=error_msg)

        video_data = await self._get_video_data_playwright(url)
        return self._parse_video_info(video_data, url)

    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载视频"""
        # 验证链接格式
        is_valid, error_msg = self.validate_url(url)
        if not is_valid:
            raise DownloaderError(url=url, message=error_msg)

        self._progress_callback = progress_callback
        self._current_progress = DownloadProgress()
        start_time = time.time()

        try:
            video_data = await self._get_video_data_playwright(url)
            video_info = self._parse_video_info(video_data, url)

            if progress_callback:
                progress_callback.on_start(video_info)

            download_url = self._extract_video_url(video_data)

            safe_title = re.sub(r'[\s\\/*?:"<>|]', "_", video_info.title).strip("_")[:80]
            if not safe_title.strip():
                safe_title = f"douyin_{video_info.video_id}"
            file_path = output_dir / f"{safe_title}.mp4"

            await self._download_file(download_url, file_path, progress_callback)

            file_size = file_path.stat().st_size if file_path.exists() else None

            result = DownloadResult(
                success=True,
                video_info=video_info,
                file_path=file_path,
                file_size=file_size,
                elapsed_time=time.time() - start_time,
            )

            if progress_callback:
                progress_callback.on_complete(result)

            return result

        except (VideoNotFoundError, DownloaderError):
            raise
        except Exception as e:
            result = DownloadResult(
                success=False,
                video_info=VideoInfo(
                    url=url,
                    platform=Platform.DOUYIN,
                    video_id=self._extract_video_id(url),
                    title="未知",
                ),
                error_message=str(e),
                elapsed_time=time.time() - start_time,
            )

            if progress_callback:
                progress_callback.on_error(e)

            return result

    async def _download_file(
        self,
        url: str,
        file_path: Path,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> None:
        """下载文件"""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.douyin.com/",
        }

        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()

                total_size = int(response.headers.get("content-length", 0))
                downloaded = 0

                with open(file_path, "wb") as f:
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size:
                            progress = DownloadProgress(
                                downloaded_bytes=downloaded,
                                total_bytes=total_size,
                                percentage=(downloaded / total_size) * 100,
                                status="downloading",
                            )
                            progress_callback.on_progress(progress)

    @staticmethod
    def _format_size(size: int) -> str:
        """格式化文件大小"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.2f} GB"

    @classmethod
    def _get_random_ua(cls) -> str:
        return random.choice(cls.USER_AGENTS)

    async def _download_file_http(self, download_url: str, file_path: Path) -> tuple[bool, int, str]:
        """用 HTTP 下载视频文件，返回 (success, file_size, error_message)"""
        headers = {
            "User-Agent": self._get_random_ua(),
            "Referer": "https://www.douyin.com/",
            "Accept": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,audio/*;q=0.6,*/*;q=0.5",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        try:
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=180) as client:
                async with client.stream("GET", download_url) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get("content-length", 0))
                    downloaded = 0
                    with open(file_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = downloaded / total_size * 100
                                print(f"\r[下载进度] {pct:.1f}% ({self._format_size(downloaded)}/{self._format_size(total_size)})", end="", flush=True)
                    print()
                    return True, file_path.stat().st_size, ""
        except Exception as e:
            return False, 0, str(e)

    async def _download_subtitle_from_aweme(self, aweme_detail: dict, srt_path: Path) -> bool:
        """从 aweme_detail 中提取字幕并保存为 SRT 文件"""
        subtitle_url = None
        for field in ["video_subtitle", "caption_infos"]:
            items = aweme_detail.get(field)
            if not items or not isinstance(items, list):
                continue
            for item in items:
                url = item.get("Url") or item.get("url") or item.get("subtitle_url")
                if url:
                    subtitle_url = url
                    break
            if subtitle_url:
                break

        if not subtitle_url:
            return False

        try:
            headers = {
                "User-Agent": self._get_random_ua(),
                "Referer": "https://www.douyin.com/",
            }
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30) as client:
                resp = await client.get(subtitle_url)
                resp.raise_for_status()
                content = resp.text
                if content.strip():
                    with open(srt_path, "w", encoding="utf-8") as f:
                        f.write(content)
                    return True
        except Exception as e:
            print(f"[字幕] 下载失败: {e}")
        return False

    async def _extract_username_from_page(self, page) -> str:
        """从抖音用户主页提取用户名"""
        try:
            title = await page.title()
            if title and "抖音" in title:
                name = title.replace("的主页 - 抖音", "").replace("的抖音", "").strip()
                if name:
                    return name
            name_el = await page.query_selector('h1[class*="name"], span[class*="nickname"], [data-e2e="user-info-nickname"]')
            if name_el:
                name = await name_el.text_content()
                if name:
                    return name.strip()
        except Exception:
            pass
        return ""

    @staticmethod
    def _get_existing_videos(folder: Path) -> set[str]:
        """获取文件夹中已下载的视频URL（通过读取元数据）"""
        existing = set()
        metadata_file = folder / "_metadata.json"
        if metadata_file.exists():
            try:
                with open(metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for video in data.get("downloaded_videos", []):
                        if video.get("url"):
                            existing.add(video["url"])
            except Exception:
                pass
        return existing

    @staticmethod
    def _save_user_metadata(folder: Path, user_url: str, user_info: dict, videos: list[dict]):
        """保存用户下载元数据到文件夹"""
        metadata = {
            "user_url": user_url,
            "username": user_info.get("username", ""),
            "work_count": user_info.get("work_count", 0),
            "video_count": user_info.get("video_count", 0),
            "non_video_count": user_info.get("non_video_count", 0),
            "last_updated": datetime.now().isoformat(),
            "downloaded_videos": videos,
        }
        metadata_file = folder / "_metadata.json"
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        urls_file = folder / "_video_urls.txt"
        with open(urls_file, "w", encoding="utf-8") as f:
            f.write(f"# 用户: {user_info.get('username', '未知')}\n")
            f.write(f"# 主页: {user_url}\n")
            f.write(f"# 作品数: {user_info.get('work_count', 0)} | 视频数: {user_info.get('video_count', 0)}\n")
            f.write(f"# 更新时间: {datetime.now().isoformat()}\n")
            f.write(f"# {'='*50}\n\n")
            for i, video in enumerate(videos, 1):
                status = "✓" if video.get("success") else "✗"
                f.write(f"{i:03d}. [{status}] {video.get('url', '')}\n")
                if video.get("title"):
                    f.write(f"     标题: {video['title']}\n")

    async def _check_login_status(self, page) -> bool:
        """检查抖音登录状态"""
        try:
            login_btn = await page.query_selector(
                'button:has-text("登录"), a:has-text("登录"), '
                'button:has-text("Login"), a:has-text("Login"), '
                'div[class*="login-btn"], button[class*="login"], '
                'div[class*="login-guide"]'
            )
            if login_btn and await login_btn.is_visible():
                return False
            avatar = await page.query_selector(
                'img[class*="avatar"], div[class*="avatar"], '
                'img[class*="Avatar"], div[class*="Avatar"]'
            )
            if avatar and await avatar.is_visible():
                return True
            return True
        except Exception:
            return True

    async def download_user_videos_stream(
        self,
        user_url: str,
        output_dir: Path,
        quality: str = "best",
        max_retries: int = 3,
    ) -> AsyncGenerator[dict, None]:
        """
        流式下载抖音用户主页视频，逐个 yield 事件。

        特性：
        - 浏览器保持打开状态，供下次复用
        - 自动创建以用户名命名的文件夹
        - 跳过已下载的视频
        - 保存元数据（视频URL列表、用户信息）
        - 区分作品数和视频数
        """
        from src.core.events import (
            make_extracting_event, make_extracted_event,
            make_downloading_event, make_downloaded_event,
            make_retrying_event, make_done_event, make_error_event,
        )
        from src.services.browser_manager import get_browser_manager

        start_time = time.time()

        # 状态变量
        succeeded_count = 0
        skipped_count = 0
        failed_list: list[dict] = []
        non_video_list: list[dict] = []
        video_urls: list[str] = []
        downloaded_urls: set[str] = set()
        work_count = 0
        video_count = 0
        username = ""
        user_folder: Optional[Path] = None
        max_retry_rounds = max_retries

        print(f"\n{'='*60}")
        print(f"[用户主页下载] 开始处理: {user_url}")
        print(f"{'='*60}\n")

        yield make_extracting_event("正在启动浏览器...")

        self._sync_native_profile()
        chrome_path = self._get_chrome_path()

        browser_manager = await get_browser_manager()
        page = await browser_manager.get_page(self.PROFILE_DIR, chrome_path)

        try:
            # ========== 第一步：访问用户主页 ==========
            print(f"[步骤1] 正在访问用户主页...")
            yield make_extracting_event("正在访问用户主页，提取视频列表...")

            await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

            # 循环检测验证码/登录
            for auth_attempt in range(10):
                has_block, block_type = await self._check_captcha(page)
                if not has_block:
                    if auth_attempt > 0:
                        print(f"[信息] ✓ 验证/登录已全部完成")
                    break
                print(f"[警告] ⚠️ 检测到 {block_type}！请在浏览器中完成... (第{auth_attempt+1}次)")
                yield make_extracting_event(f"检测到{block_type}，请在浏览器中完成验证...")
                resolved = await self._wait_for_auth_resolved(page, 120)
                if not resolved:
                    await self._save_debug_info(page, "auth_timeout")
                    yield make_error_event(f"验证码/登录超时未完成")
                    return
                print(f"[信息] ✓ {block_type} 已通过")
                await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))
            else:
                await self._save_debug_info(page, "max_auth_retries")
                yield make_error_event("验证/登录重试次数过多")
                return

            # 等待视频链接
            video_links_found = False
            for load_attempt in range(5):
                print(f"[步骤1] 等待页面加载... (第{load_attempt+1}次)")
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass

                has_block, block_type = await self._check_captcha(page)
                if has_block:
                    print(f"[警告] ⚠️ 检测到 {block_type}！请在浏览器中完成...")
                    resolved = await self._wait_for_auth_resolved(page, 120)
                    if not resolved:
                        yield make_error_event(f"验证码/登录超时未完成")
                        return
                    await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))
                    continue

                try:
                    await page.wait_for_selector('a[href*="/video/"]', timeout=15000)
                    print(f"[步骤1] ✓ 视频链接已加载")
                    is_logged_in = await self._check_login_status(page)
                    if not is_logged_in:
                        print(f"[警告] ⚠️ 抖音未登录！未登录状态下可能无法获取全部视频")
                        yield make_extracting_event("⚠️ 未登录抖音，可能无法获取全部视频。建议登录后重试。")
                        await page.wait_for_timeout(3000)
                    video_links_found = True
                    break
                except Exception:
                    await page.wait_for_timeout(5000)

            if not video_links_found:
                print(f"[警告] 刷新页面重试...")
                await page.reload(wait_until="networkidle", timeout=60000)
                await page.wait_for_timeout(8000)
                try:
                    await page.wait_for_selector('a[href*="/video/"]', timeout=30000)
                    video_links_found = True
                except Exception:
                    await self._save_debug_info(page, "no_videos_after_refresh")
                    yield make_error_event("无法加载视频列表，请检查网络或重新登录")
                    return

            # ========== 提取用户名并创建文件夹 ==========
            username = await self._extract_username_from_page(page)
            if username:
                safe_username = re.sub(r'[\\/*?:"<>|]', "_", username).strip("_")[:50]
                user_folder = output_dir / safe_username
            else:
                user_folder = output_dir / f"douyin_user_{int(time.time())}"

            user_folder.mkdir(parents=True, exist_ok=True)
            print(f"[用户主页下载] 用户名: {username or '未知'}")
            print(f"[用户主页下载] 保存目录: {user_folder}")

            downloaded_urls = self._get_existing_videos(user_folder)
            if downloaded_urls:
                print(f"[信息] 发现 {len(downloaded_urls)} 个已下载的视频，将跳过")

            await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

            # ========== 提取作品数和视频链接 ==========
            extract_js = '''() => {
                const containers = document.querySelectorAll('div[class*="userNewUi"]');
                const links = new Set();
                containers.forEach(container => {
                    const aTags = container.querySelectorAll('a[href]');
                    aTags.forEach(a => {
                        if (a.closest('.user-page-footer')) return;
                        const href = a.getAttribute('href');
                        if (href && href.includes('/video/')) links.add(href);
                    });
                });
                return Array.from(links);
            }'''

            # 获取作品总数
            try:
                work_count = await page.evaluate('''() => {
                    const tabs = document.querySelectorAll('span, div');
                    for (const el of tabs) {
                        const text = el.textContent || '';
                        const match = text.match(/作品[\\s]*([0-9]+)/);
                        if (match) return parseInt(match[1]);
                    }
                    return 0;
                }''') or 0
                if work_count:
                    print(f"[步骤1] 页面显示该用户有 {work_count} 个作品")
            except Exception:
                work_count = 0

            # 滚动前：保存页面快照 + 检测可滚动元素
            await self._save_debug_info(page, "before_scroll")
            try:
                scroll_debug = await page.evaluate('''() => {
                    const results = [];
                    const candidates = [
                        document.scrollingElement,
                        document.documentElement,
                        document.body,
                        ...document.querySelectorAll('[class*="user-tab-content"]'),
                        ...document.querySelectorAll('div[class*="userNewUi"]'),
                        ...document.querySelectorAll('[class*="container"]'),
                        ...document.querySelectorAll('main'),
                    ];
                    for (const el of candidates) {
                        if (!el) continue;
                        const tag = el.tagName || 'unknown';
                        const cls = (el.className || '').toString().substring(0, 80);
                        const sh = el.scrollHeight;
                        const ch = el.clientHeight;
                        const st = el.scrollTop;
                        const ov = getComputedStyle(el).overflow + '/' + getComputedStyle(el).overflowY;
                        if (sh > ch + 10) {
                            results.push(`SCROLLABLE ${tag} cls="${cls}" scrollH=${sh} clientH=${ch} scrollTop=${st} overflow=${ov}`);
                        } else {
                            results.push(`NOT-SCROLLABLE ${tag} cls="${cls}" scrollH=${sh} clientH=${ch} overflow=${ov}`);
                        }
                    }
                    return results;
                }''')
                for line in scroll_debug:
                    print(f"[滚动调试] {line}")
            except Exception as e:
                print(f"[滚动调试] 检测失败: {e}")

            # 滚动加载
            print(f"[步骤1] 正在滚动加载视频列表...")
            prev_count = 0
            no_change_rounds = 0

            for i in range(100):
                try:
                    hrefs = await page.evaluate(extract_js)
                except Exception:
                    await page.wait_for_timeout(self._random_delay((0.8, 1.5)))
                    continue

                current_count = len(hrefs)

                if work_count and current_count >= work_count:
                    print(f"[步骤1] ✓ 已加载全部 {current_count}/{work_count} 个作品链接")
                    break

                if current_count != prev_count:
                    print(f"[步骤1] 已发现 {current_count}/{work_count or '?'} 个视频链接...")
                    no_change_rounds = 0
                else:
                    no_change_rounds += 1
                    if no_change_rounds >= 5:
                        if work_count and current_count < work_count:
                            print(f"[警告] 滚动后无法加载更多视频（可能需要登录）")
                        break
                    print(f"[步骤1] 未发现新内容，等待页面加载 ({no_change_rounds}/5)...")
                    await page.wait_for_timeout(self._random_delay(self.SCROLL_RETRY_DELAY))
                    continue
                prev_count = current_count

                await page.mouse.move(random.randint(900, 1100), random.randint(550, 700))
                delta_y = random.randint(600, 1800)
                await page.mouse.wheel(0, delta_y)
                await page.wait_for_timeout(self._random_delay(self.SCROLL_DELAY))

            # 提取链接
            hrefs = await page.evaluate(extract_js)
            for href in hrefs:
                if href.startswith('/video/'):
                    video_urls.append(f"https://www.douyin.com{href}")
                elif 'douyin.com/video/' in href:
                    video_urls.append(href)

            video_count = len(video_urls)
            non_video_count = work_count - video_count if work_count > video_count else 0

            print(f"\n[步骤1] 完成！")
            print(f"  - 作品总数: {work_count}")
            print(f"  - 视频数量: {video_count}")
            if non_video_count > 0:
                print(f"  - 非视频作品: {non_video_count} (图文等)")

            if video_count == 0:
                await self._save_debug_info(page, "no_videos")
                yield make_error_event("未找到任何视频，可能需要登录或完成验证")
                return

            yield make_extracted_event(
                total=video_count,
                work_count=work_count,
                non_video_count=non_video_count,
                message=f"找到 {video_count} 个视频（作品 {work_count} 个），开始下载...",
            )

            # ========== 第二步：逐个下载视频 ==========
            print(f"\n[步骤2] 开始下载视频...")
            downloaded_videos_info: list[dict] = []

            for idx, video_url in enumerate(video_urls, 1):
                # 检查是否已下载
                if video_url in downloaded_urls:
                    skipped_count += 1
                    print(f"[视频 {idx}/{video_count}] 已存在，跳过")
                    downloaded_videos_info.append({"url": video_url, "title": "", "success": True, "skipped": True})
                    yield make_downloaded_event(
                        index=idx, total=video_count, title="(已存在)",
                        success=True, skipped=True,
                        succeeded_so_far=succeeded_count, skipped_count=skipped_count,
                    )
                    continue

                print(f"\n{'─'*50}")
                print(f"[视频 {idx}/{video_count}] {video_url}")

                yield make_downloading_event(
                    index=idx, total=video_count, url=video_url,
                    title=f"视频 {idx}",
                    succeeded_so_far=succeeded_count,
                    remaining=video_count - succeeded_count - len(failed_list) - skipped_count,
                )

                video_data = {}
                video_captured = asyncio.Event()

                async def handle_response(response):
                    nonlocal video_data
                    try:
                        if "aweme/v1/web/aweme/detail" in response.url or "/aweme/detail" in response.url:
                            if response.status == 200:
                                data = await response.json()
                                if data.get("aweme_detail"):
                                    video_data = data["aweme_detail"]
                                    video_captured.set()
                    except Exception:
                        pass

                page.on("response", handle_response)

                try:
                    print(f"[视频 {idx}/{video_count}] 正在获取下载地址...")
                    await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(self._random_delay((1.0, 2.0)))

                    has_block, block_type = await self._check_captcha(page)
                    if has_block:
                        print(f"[视频 {idx}/{video_count}] ⚠️ 检测到 {block_type}！")
                        resolved = await self._wait_for_auth_resolved(page, 120)
                        if not resolved:
                            failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": "验证超时"})
                            yield make_downloaded_event(
                                index=idx, total=video_count, title=f"视频 {idx}",
                                success=False, error="验证码超时", permanently_failed=True,
                            )
                            page.remove_listener("response", handle_response)
                            continue
                        await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))

                    try:
                        await asyncio.wait_for(video_captured.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        print(f"[视频 {idx}/{video_count}] 获取超时，尝试从页面提取...")

                    page.remove_listener("response", handle_response)

                    if not video_data:
                        video_data = await self._extract_from_page(page)

                    if not video_data:
                        print(f"[视频 {idx}/{video_count}] ✗ 无法获取视频信息")
                        failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": "无法获取视频信息"})
                        yield make_downloaded_event(
                            index=idx, total=video_count, title=f"视频 {idx}",
                            success=False, error="无法获取视频信息", permanently_failed=True,
                        )
                        continue

                    title = video_data.get("desc", f"视频 {idx}") or f"视频 {idx}"

                    # 提取下载地址 (复用已有方法)
                    try:
                        download_url = self._extract_video_url(video_data)
                    except DownloaderError:
                        download_url = None

                    if not download_url:
                        print(f"[视频 {idx}/{video_count}] ✗ 无法获取下载地址")
                        failed_list.append({"url": video_url, "title": title, "error": "无法获取下载地址"})
                        yield make_downloaded_event(
                            index=idx, total=video_count, title=title,
                            success=False, error="无法获取下载地址", permanently_failed=True,
                        )
                        continue

                    # 从URL提取视频ID，用于文件名去重
                    video_id_match = re.search(r'/video/(\d+)', video_url)
                    video_id = video_id_match.group(1)[-8:] if video_id_match else ""

                    safe_title = re.sub(r'[\s\\/*?:"<>|]', "_", title).strip("_")[:80]
                    if not safe_title.strip():
                        safe_title = f"douyin_{idx}"
                    filename = f"{safe_title}_{video_id}.mp4" if video_id else f"{safe_title}.mp4"
                    file_path = user_folder / filename

                    old_file_path = user_folder / f"{safe_title}.mp4"

                    if file_path.exists() or (old_file_path.exists() and old_file_path != file_path):
                        existing = file_path if file_path.exists() else old_file_path
                        print(f"[视频 {idx}/{video_count}] 文件已存在，跳过: {existing.name}")
                        skipped_count += 1
                        downloaded_urls.add(video_url)
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "skipped": True, "file_path": str(existing)})
                        yield make_downloaded_event(
                            index=idx, total=video_count, title=title,
                            success=True, skipped=True, file_path=str(existing),
                        )
                        continue

                    print(f"[视频 {idx}/{video_count}] 正在下载: {title[:30]}...")
                    success, file_size, error_msg = await self._download_file_http(download_url, file_path)

                    if success:
                        succeeded_count += 1
                        downloaded_urls.add(video_url)
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "file_path": str(file_path)})
                        print(f"[视频 {idx}/{video_count}] ✓ 下载成功: {self._format_size(file_size)}")

                        srt_path = file_path.with_suffix(".srt")
                        has_subtitle = await self._download_subtitle_from_aweme(video_data, srt_path)
                        if has_subtitle:
                            print(f"[视频 {idx}/{video_count}] ✓ 字幕已保存: {srt_path.name}")

                        yield make_downloaded_event(
                            index=idx, total=video_count, title=title,
                            success=True, file_path=str(file_path),
                            file_size_human=self._format_size(file_size),
                            has_subtitle=has_subtitle,
                            succeeded_so_far=succeeded_count,
                            remaining=video_count - succeeded_count - len(failed_list) - skipped_count,
                        )
                        await asyncio.sleep(self._random_delay(self.DOWNLOAD_INTERVAL) / 1000)
                    else:
                        print(f"[视频 {idx}/{video_count}] ✗ 下载失败: {error_msg}")
                        failed_list.append({"url": video_url, "title": title, "error": error_msg})
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": False, "error": error_msg})
                        yield make_downloaded_event(
                            index=idx, total=video_count, title=title,
                            success=False, error=error_msg, permanently_failed=True,
                        )

                except Exception as e:
                    print(f"[视频 {idx}/{video_count}] ✗ 异常: {str(e)}")
                    page.remove_listener("response", handle_response)
                    failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": str(e)})
                    yield make_downloaded_event(
                        index=idx, total=video_count, title=f"视频 {idx}",
                        success=False, error=str(e), permanently_failed=True,
                    )

                await page.wait_for_timeout(self._random_delay(self.VIDEO_INTERVAL))

            # ========== 第三步：失败视频重试 ==========
            retry_round = 0
            while failed_list and retry_round < max_retry_rounds:
                retry_round += 1
                failed_urls = [f["url"] for f in failed_list]
                retry_count = len(failed_urls)

                print(f"\n{'='*60}")
                print(f"[重试 第{retry_round}/{max_retry_rounds}轮] 有 {retry_count} 个视频下载失败，准备重试...")
                print(f"{'='*60}")

                yield make_retrying_event(
                    round_num=retry_round, max_rounds=max_retry_rounds,
                    failed_count=retry_count,
                )

                # 回到用户首页重新获取链接
                print(f"[重试] 回到用户首页重新获取视频链接...")
                await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

                has_block, block_type = await self._check_captcha(page)
                if has_block:
                    print(f"[重试] ⚠️ 检测到 {block_type}！请在浏览器中完成...")
                    resolved = await self._wait_for_auth_resolved(page, 120)
                    if not resolved:
                        print(f"[重试] 验证超时，跳过本轮重试")
                        break
                    await page.wait_for_timeout(int(random.uniform(5, 8) * 1000))

                try:
                    await page.wait_for_selector('a[href*="/video/"]', timeout=15000)
                except Exception:
                    print(f"[重试] 无法加载视频列表，跳过本轮重试")
                    break

                # 滚动加载所有视频
                print(f"[重试] 滚动加载视频列表...")
                for _ in range(30):
                    await page.mouse.move(random.randint(900, 1100), random.randint(550, 700))
                    await page.mouse.wheel(0, random.randint(600, 1800))
                    await page.wait_for_timeout(self._random_delay(self.SCROLL_DELAY))
                    hrefs = await page.evaluate(extract_js)
                    if work_count and len(hrefs) >= work_count:
                        break

                old_failed_list = failed_list.copy()
                failed_list.clear()

                for idx, failed_item in enumerate(old_failed_list, 1):
                    video_url = failed_item["url"]

                    print(f"\n{'─'*50}")
                    print(f"[重试 {idx}/{retry_count}] {video_url}")

                    yield make_downloading_event(
                        index=idx, total=retry_count, url=video_url,
                        title=failed_item.get("title", f"视频 {idx}"),
                        is_retry=True, retry_round=retry_round,
                    )

                    video_data = {}
                    video_captured = asyncio.Event()

                    async def handle_response_retry(response):
                        nonlocal video_data
                        try:
                            if "aweme/v1/web/aweme/detail" in response.url or "/aweme/detail" in response.url:
                                if response.status == 200:
                                    data = await response.json()
                                    if data.get("aweme_detail"):
                                        video_data = data["aweme_detail"]
                                        video_captured.set()
                        except Exception:
                            pass

                    page.on("response", handle_response_retry)

                    try:
                        await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
                        await page.wait_for_timeout(self._random_delay((1.5, 2.5)))

                        has_block, block_type = await self._check_captcha(page)
                        if has_block:
                            print(f"[重试 {idx}/{retry_count}] ⚠️ 检测到 {block_type}！")
                            resolved = await self._wait_for_auth_resolved(page, 120)
                            if not resolved:
                                failed_list.append(failed_item)
                                page.remove_listener("response", handle_response_retry)
                                continue
                            await page.wait_for_timeout(int(random.uniform(5, 8) * 1000))

                        try:
                            await asyncio.wait_for(video_captured.wait(), timeout=15)
                        except asyncio.TimeoutError:
                            pass

                        page.remove_listener("response", handle_response_retry)

                        if not video_data:
                            video_data = await self._extract_from_page(page)

                        if not video_data:
                            print(f"[重试 {idx}/{retry_count}] ✗ 仍无法获取视频信息")
                            failed_list.append(failed_item)
                            continue

                        title = video_data.get("desc", failed_item.get("title", f"视频 {idx}")) or f"视频 {idx}"

                        try:
                            download_url = self._extract_video_url(video_data)
                        except DownloaderError:
                            download_url = None

                        if not download_url:
                            print(f"[重试 {idx}/{retry_count}] ✗ 仍无法获取下载地址")
                            failed_list.append({"url": video_url, "title": title, "error": "无法获取下载地址"})
                            continue

                        safe_title = re.sub(r'[\s\\/*?:"<>|]', "_", title).strip("_")[:80]
                        if not safe_title.strip():
                            safe_title = f"douyin_retry_{idx}"
                        file_path = user_folder / f"{safe_title}.mp4"

                        print(f"[重试 {idx}/{retry_count}] 正在下载: {title[:30]}...")
                        success, file_size, error_msg = await self._download_file_http(download_url, file_path)

                        if success:
                            succeeded_count += 1
                            downloaded_urls.add(video_url)
                            for v in downloaded_videos_info:
                                if v.get("url") == video_url:
                                    v["success"] = True
                                    v["file_path"] = str(file_path)
                                    v.pop("error", None)
                                    break
                            else:
                                downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "file_path": str(file_path)})

                            print(f"[重试 {idx}/{retry_count}] ✓ 重试成功: {self._format_size(file_size)}")
                            yield make_downloaded_event(
                                index=idx, total=retry_count, title=title,
                                success=True, file_path=str(file_path),
                                file_size_human=self._format_size(file_size),
                                is_retry=True, retry_round=retry_round,
                            )
                        else:
                            print(f"[重试 {idx}/{retry_count}] ✗ 重试仍失败: {error_msg}")
                            failed_list.append({"url": video_url, "title": title, "error": error_msg})

                    except Exception as e:
                        print(f"[重试 {idx}/{retry_count}] ✗ 异常: {str(e)}")
                        page.remove_listener("response", handle_response_retry)
                        failed_list.append({"url": video_url, "title": failed_item.get("title", f"视频 {idx}"), "error": str(e)})

                    await page.wait_for_timeout(self._random_delay(self.VIDEO_INTERVAL))

                print(f"\n[重试 第{retry_round}轮完成] 本轮成功: {retry_count - len(failed_list)} | 仍失败: {len(failed_list)}")

                if not failed_list:
                    print(f"[重试] ✓ 所有视频已成功下载!")
                    break

            # ========== 保存元数据 ==========
            user_info = {
                "username": username,
                "work_count": work_count,
                "video_count": video_count,
                "non_video_count": non_video_count,
            }
            self._save_user_metadata(user_folder, user_url, user_info, downloaded_videos_info)
            print(f"\n[信息] 已保存元数据到: {user_folder}")

            browser_manager.keep_alive()

        except Exception as e:
            print(f"\n[错误] {str(e)}")
            yield make_error_event(str(e))
            return

        # ========== 完成 ==========
        elapsed = round(time.time() - start_time, 1)
        print(f"\n{'='*60}")
        print(f"[完成] 作品: {work_count} | 视频: {video_count} | 非视频: {non_video_count}")
        print(f"[完成] 新下载: {succeeded_count} | 已存在跳过: {skipped_count} | 失败: {len(failed_list)}")
        print(f"[完成] 耗时: {elapsed}s")
        print(f"[完成] 保存目录: {user_folder}")
        print(f"{'='*60}\n")

        yield make_done_event(
            total=video_count,
            work_count=work_count,
            non_video_count=non_video_count,
            succeeded=succeeded_count,
            skipped=skipped_count,
            failed=len(failed_list),
            skipped_videos=failed_list,
            elapsed_time=elapsed,
            folder_path=str(user_folder),
            username=username,
        )

    async def extract_user_video_urls(self, user_url: str, max_scroll: int = 50, interactive: bool = True) -> list[str]:
        """
        从抖音用户主页提取所有视频链接

        打开用户主页，在 class 包含 'userNewUi' 的 div 下查找所有 a 标签的 href，
        自动向下滚动以加载更多视频。

        Args:
            user_url: 抖音用户主页URL
            max_scroll: 最大滚动次数，防止无限滚动
            interactive: 是否交互模式（CLI模式为True，API模式为False）

        Returns:
            视频URL列表
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise DownloaderError(url=user_url, message="请安装 playwright: pip install playwright")

        # 将系统浏览器的登录态同步到独立 profile，避免文件锁冲突
        self._sync_native_profile()

        chrome_path = self._get_chrome_path()
        video_urls: list[str] = []

        async with async_playwright() as p:
            launch_options = {
                "user_data_dir": str(self.PROFILE_DIR),
                "headless": False,
                "args": [
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
                "viewport": {"width": 1280, "height": 800},
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            }

            if chrome_path:
                launch_options["executable_path"] = chrome_path

            print(f"[抖音下载] 正在启动浏览器...")
            context = await p.chromium.launch_persistent_context(**launch_options)
            print(f"[抖音下载] 浏览器已启动")

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 注入反检测脚本
                await page.add_init_script("""
                    // 隐藏 webdriver 标识
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    delete navigator.__proto__.webdriver;

                    // 伪造插件
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [
                            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                            { name: 'Native Client', filename: 'internal-nacl-plugin' }
                        ]
                    });

                    // 语言设置
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

                    // Chrome 对象
                    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };

                    // 隐藏自动化特征
                    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });
                    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                """)

                # 访问用户主页
                await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

                if interactive:
                    # 交互模式：等待用户手动完成验证
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: input("\n>>> 浏览器已打开，如需完成验证请在浏览器中操作，完成后回到此处按 回车键 继续...\n")
                    )
                    await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))
                else:
                    # API模式：循环检测验证码/登录，直到页面正常加载
                    # 等待页面稳定
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass

                    # 循环检测验证码/登录（可能反复出现）
                    auth_ok = await self._wait_and_retry_auth(page, max_retries=10)
                    if not auth_ok:
                        await self._save_debug_info(page, "auth_timeout")
                        raise DownloaderError(url=user_url, message="验证码/登录超时未完成")

                    # 等待页面完全加载（最多重试5次）
                    video_links_found = False
                    for load_attempt in range(5):
                        print(f"[抖音下载] 等待页面加载... (第{load_attempt+1}次)")

                        # 等待网络空闲
                        try:
                            await page.wait_for_load_state("networkidle", timeout=30000)
                        except Exception:
                            pass

                        # 检测是否有验证码/登录
                        has_block, block_type = await self._check_captcha(page)
                        if has_block:
                            print(f"[抖音下载] ⚠️ 检测到 {block_type}！请在浏览器中完成...")
                            resolved = await self._wait_for_auth_resolved(page, 120)
                            if not resolved:
                                await self._save_debug_info(page, "auth_timeout_2")
                                raise DownloaderError(url=user_url, message="验证码/登录超时未完成")
                            # 等待页面刷新
                            wait_time = random.uniform(10, 12)
                            print(f"[抖音下载] 等待页面刷新 ({wait_time:.1f}s)...")
                            await page.wait_for_timeout(int(wait_time * 1000))
                            continue

                        # 等待实际视频链接出现（不只是容器）
                        try:
                            await page.wait_for_selector('a[href*="/video/"]', timeout=15000)
                            print(f"[抖音下载] ✓ 视频链接已加载")
                            video_links_found = True
                            break
                        except Exception:
                            # 检查是否有加载指示器
                            loading = await page.query_selector('div[class*="loading"]')
                            if loading:
                                print(f"[抖音下载] 页面正在加载中，继续等待...")
                                await page.wait_for_timeout(5000)
                            else:
                                print(f"[抖音下载] 未找到视频链接，等待页面继续加载...")
                                await page.wait_for_timeout(5000)

                    if not video_links_found:
                        # 最后一次尝试 - 刷新页面
                        print(f"[抖音下载] 多次尝试后仍未找到视频链接，刷新页面重试...")
                        await page.reload(wait_until="networkidle", timeout=60000)
                        await page.wait_for_timeout(8000)  # 刷新后多等一会儿
                        try:
                            await page.wait_for_selector('a[href*="/video/"]', timeout=30000)
                            print(f"[抖音下载] ✓ 刷新后找到视频链接")
                            video_links_found = True
                        except Exception:
                            await self._save_debug_info(page, "no_videos_after_refresh")
                            raise DownloaderError(url=user_url, message="无法加载视频列表，请检查网络或重新登录")

                    # 额外等待确保内容渲染完成
                    await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

                # 提取链接的JS脚本（支持多种容器选择器）
                extract_js = '''() => {
                    const links = new Set();

                    // 尝试多种容器选择器
                    const selectors = [
                        'div[class*="userNewUi"]',
                        'div[class*="user-post"]',
                        'div[class*="video-list"]',
                        'ul[class*="video"]',
                        'main'
                    ];

                    for (const selector of selectors) {
                        const containers = document.querySelectorAll(selector);
                        containers.forEach(container => {
                            const aTags = container.querySelectorAll('a[href]');
                            aTags.forEach(a => {
                                // 排除底部推荐区
                                if (a.closest('.user-page-footer')) return;
                                if (a.closest('[class*="recommend"]')) return;
                                const href = a.getAttribute('href');
                                if (href && href.includes('/video/')) {
                                    links.add(href);
                                }
                            });
                        });
                    }

                    return Array.from(links);
                }'''

                # 安全执行 evaluate（跨导航时可能失败）
                async def safe_evaluate(js: str, default=None):
                    try:
                        return await page.evaluate(js)
                    except Exception:
                        await page.wait_for_timeout(self._random_delay((0.8, 1.5)))
                        try:
                            return await page.evaluate(js)
                        except Exception:
                            return default if default is not None else []

                # 滚动加载所有视频
                print(f"[抖音下载] 开始滚动加载视频列表...")
                prev_count = 0
                no_change_rounds = 0

                for i in range(max_scroll):
                    hrefs = await safe_evaluate(extract_js)

                    current_count = len(hrefs)
                    if current_count > 0:
                        print(f"[抖音下载] 滚动 {i+1}: 已发现 {current_count} 个视频链接")

                    if current_count == prev_count:
                        no_change_rounds += 1
                        if no_change_rounds >= 3:
                            print(f"[抖音下载] 连续3次无新内容，停止滚动")
                            break
                        # 页面加载慢时，等久一点再重试
                        print(f"[抖音下载] 未发现新内容，等待页面加载 ({no_change_rounds}/3)...")
                        await page.wait_for_timeout(self._random_delay(self.SCROLL_RETRY_DELAY))
                        continue
                    else:
                        no_change_rounds = 0
                    prev_count = current_count

                    # 模拟真实用户滚动 - 先将鼠标移到页面中央，再触发 wheel 事件
                    await page.mouse.move(random.randint(900, 1100), random.randint(550, 700))
                    delta_y = random.randint(800, 1500)
                    await page.mouse.wheel(0, delta_y)
                    await page.wait_for_timeout(self._random_delay(self.SCROLL_DELAY))

                # 最终提取一次
                hrefs = await safe_evaluate(extract_js)
                print(f"[抖音下载] 最终提取到 {len(hrefs)} 个链接")

                # 如果没有找到任何视频，保存调试信息
                if len(hrefs) == 0:
                    print(f"[抖音下载] ⚠️ 未找到视频链接")
                    await self._save_debug_info(page, "no_videos")

                    # 调试：打印页面上所有链接
                    all_links = await page.evaluate('''() => {
                        const links = [];
                        document.querySelectorAll('a[href]').forEach(a => {
                            const href = a.getAttribute('href');
                            if (href && !href.startsWith('javascript:')) {
                                links.push(href.substring(0, 80));
                            }
                        });
                        return links.slice(0, 20);  // 只取前20个
                    }''')
                    print(f"[抖音下载] 页面链接示例 (共{len(all_links)}个): {all_links[:5]}")

                    # 检查是否还有验证码/登录
                    has_block, block_type = await self._check_captcha(page)
                    if has_block:
                        print(f"[抖音下载] ⚠️ 页面仍有 {block_type}，请手动完成验证")

                # 将相对路径转换为完整URL，只保留视频链接
                for href in hrefs:
                    if href.startswith('/video/'):
                        full_url = f"https://www.douyin.com{href}"
                        video_urls.append(full_url)
                    elif 'douyin.com/video/' in href:
                        video_urls.append(href)

                print(f"[抖音下载] 共提取 {len(video_urls)} 个有效视频链接")

                # 保存视频URL列表到调试日志
                if video_urls:
                    self._save_video_urls_log(user_url, video_urls)

            finally:
                await context.close()

        return video_urls

    async def extract_user_videos_with_download_urls(
        self,
        user_url: str,
        max_scroll: int = 50,
        on_progress: Optional[callable] = None,
    ) -> list[dict]:
        """
        从抖音用户主页提取所有视频的下载地址（一次性，只开一次浏览器）

        Args:
            user_url: 抖音用户主页URL
            max_scroll: 最大滚动次数
            on_progress: 进度回调 (current, total, video_info)

        Returns:
            视频信息列表，每个元素包含:
            {
                "url": 视频页面URL,
                "title": 标题,
                "author": 作者,
                "download_url": 真实下载地址,
                "thumbnail": 封面图,
            }
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise DownloaderError(url=user_url, message="请安装 playwright: pip install playwright")

        self._sync_native_profile()
        chrome_path = self._get_chrome_path()
        results: list[dict] = []

        async with async_playwright() as p:
            launch_options = {
                "user_data_dir": str(self.PROFILE_DIR),
                "headless": False,
                "args": [
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
                "viewport": {"width": 1280, "height": 800},
                "ignore_default_args": ["--enable-automation", "--no-sandbox"],
            }

            if chrome_path:
                launch_options["executable_path"] = chrome_path

            print(f"[抖音下载] 正在启动浏览器...")
            context = await p.chromium.launch_persistent_context(**launch_options)
            print(f"[抖音下载] 浏览器已启动")

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 注入反检测脚本
                await page.add_init_script("""
                    // 隐藏 webdriver 标识
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    delete navigator.__proto__.webdriver;

                    // 伪造插件
                    Object.defineProperty(navigator, 'plugins', {
                        get: () => [
                            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                            { name: 'Native Client', filename: 'internal-nacl-plugin' }
                        ]
                    });

                    // 语言设置
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

                    // Chrome 对象
                    window.chrome = { runtime: {}, loadTimes: () => {}, csi: () => {} };

                    // 隐藏自动化特征
                    Object.defineProperty(navigator, 'maxTouchPoints', { get: () => 1 });
                    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
                """)

                # ========== 第一步：获取所有视频页面链接 ==========
                print(f"[抖音下载] 正在访问用户主页: {user_url}")
                await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

                # 等待页面加载
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass
                try:
                    await page.wait_for_selector('div[class*="userNewUi"]', timeout=60000)
                except Exception:
                    pass
                await page.wait_for_timeout(self._random_delay(self.PAGE_LOAD_DELAY))

                # 提取链接的JS脚本
                extract_js = '''() => {
                    const containers = document.querySelectorAll('div[class*="userNewUi"]');
                    const links = new Set();
                    containers.forEach(container => {
                        const aTags = container.querySelectorAll('a[href]');
                        aTags.forEach(a => {
                            if (a.closest('.user-page-footer')) return;
                            const href = a.getAttribute('href');
                            if (href && href.includes('/video/')) links.add(href);
                        });
                    });
                    return Array.from(links);
                }'''

                # 滚动加载所有视频
                print(f"[抖音下载] 正在滚动加载视频列表...")
                prev_count = 0
                no_change_rounds = 0

                for i in range(max_scroll):
                    try:
                        hrefs = await page.evaluate(extract_js)
                    except Exception:
                        await page.wait_for_timeout(self._random_delay((0.8, 1.5)))
                        continue

                    current_count = len(hrefs)
                    print(f"[抖音下载] 已发现 {current_count} 个视频...")

                    if current_count == prev_count:
                        no_change_rounds += 1
                        if no_change_rounds >= 3:
                            break
                        print(f"[抖音下载] 未发现新内容，等待页面加载 ({no_change_rounds}/3)...")
                        await page.wait_for_timeout(self._random_delay(self.SCROLL_RETRY_DELAY))
                        continue
                    else:
                        no_change_rounds = 0
                    prev_count = current_count

                    # 模拟真实用户滚动 - 先将鼠标移到页面中央，再触发 wheel 事件
                    await page.mouse.move(random.randint(900, 1100), random.randint(550, 700))
                    delta_y = random.randint(800, 1500)
                    await page.mouse.wheel(0, delta_y)
                    await page.wait_for_timeout(self._random_delay(self.SCROLL_DELAY))

                # 最终提取
                hrefs = await page.evaluate(extract_js)
                video_urls = []
                for href in hrefs:
                    if href.startswith('/video/'):
                        video_urls.append(f"https://www.douyin.com{href}")
                    elif 'douyin.com/video/' in href:
                        video_urls.append(href)

                total = len(video_urls)
                print(f"[抖音下载] 共找到 {total} 个视频，开始获取下载地址...")

                # 保存视频URL列表到调试日志
                if video_urls:
                    self._save_video_urls_log(user_url, video_urls)

                # ========== 第二步：逐个获取下载地址 ==========
                for idx, video_url in enumerate(video_urls, 1):
                    video_info = {
                        "url": video_url,
                        "title": f"视频 {idx}",
                        "author": None,
                        "download_url": None,
                        "thumbnail": None,
                        "error": None,
                    }

                    try:
                        # 设置网络监听捕获视频信息
                        video_data = {}
                        video_captured = asyncio.Event()

                        async def handle_response(response):
                            nonlocal video_data
                            try:
                                if "aweme/v1/web/aweme/detail" in response.url or "/aweme/detail" in response.url:
                                    if response.status == 200:
                                        data = await response.json()
                                        if data.get("aweme_detail"):
                                            video_data = data["aweme_detail"]
                                            video_captured.set()
                            except Exception:
                                pass

                        page.on("response", handle_response)

                        # 访问视频页面
                        print(f"[抖音下载] [{idx}/{total}] 获取下载地址...")
                        await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)

                        # 等待捕获
                        try:
                            await asyncio.wait_for(video_captured.wait(), timeout=10)
                        except asyncio.TimeoutError:
                            pass

                        # 移除监听器
                        page.remove_listener("response", handle_response)

                        if video_data:
                            # 提取信息
                            video_info["title"] = video_data.get("desc", f"视频 {idx}") or f"视频 {idx}"
                            video_info["author"] = video_data.get("author", {}).get("nickname")
                            video_info["thumbnail"] = video_data.get("video", {}).get("cover", {}).get("url_list", [None])[0]

                            # 提取下载地址
                            video = video_data.get("video", {})
                            download_url = None

                            # 方法1: play_addr
                            play_addr = video.get("play_addr", {})
                            url_list = play_addr.get("url_list", [])
                            if url_list:
                                download_url = url_list[0].replace("playwm", "play")

                            # 方法2: bit_rate
                            if not download_url:
                                bit_rate = video.get("bit_rate", [])
                                if bit_rate:
                                    sorted_rates = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
                                    play_addr = sorted_rates[0].get("play_addr", {})
                                    url_list = play_addr.get("url_list", [])
                                    if url_list:
                                        download_url = url_list[0]

                            video_info["download_url"] = download_url
                        else:
                            video_info["error"] = "无法获取视频信息"

                    except Exception as e:
                        video_info["error"] = str(e)

                    results.append(video_info)

                    # 进度回调
                    if on_progress:
                        on_progress(idx, total, video_info)

                    # 随机延迟避免请求过快
                    await page.wait_for_timeout(self._random_delay(self.VIDEO_INTERVAL))

            finally:
                print(f"[抖音下载] 关闭浏览器...")
                await context.close()

        print(f"[抖音下载] 完成！成功获取 {sum(1 for r in results if r.get('download_url'))} 个下载地址")
        return results

    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载音频"""
        return await self.download(url, output_dir, "best", progress_callback)
