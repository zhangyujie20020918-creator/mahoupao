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
from pathlib import Path
from typing import Optional
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

    @staticmethod
    def is_user_profile_url(url: str) -> bool:
        """检查是否为用户主页URL"""
        return "/user/" in url

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
        """获取本地 Chrome/Edge 浏览器路径"""
        possible_paths = [
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        return None

    def _get_native_user_data_dir(self) -> Optional[Path]:
        """获取系统浏览器的用户数据目录（与 _get_chrome_path 同序，保证对应）"""
        candidates = [
            Path(os.path.expandvars(r"%LocalAppData%\Microsoft\Edge\User Data")),
            Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data")),
        ]
        for p in candidates:
            if (p / "Default").exists():
                return p
        return None

    def _sync_native_profile(self) -> None:
        """
        将系统浏览器（Edge/Chrome）的配置、登录态、网站缓存同步到独立 profile 目录。
        系统浏览器运行时 User Data 目录有文件锁，无法直接共用，
        因此复制关键文件到 PROFILE_DIR 后再启动新实例。
        """
        native_dir = self._get_native_user_data_dir()
        if not native_dir:
            return

        target = self.PROFILE_DIR

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

        # 将系统浏览器的登录态同步到独立 profile，避免文件锁冲突
        self._sync_native_profile()

        video_data = {}
        chrome_path = self._get_chrome_path()

        async with async_playwright() as p:
            launch_options = {
                "user_data_dir": str(self.PROFILE_DIR),
                "headless": False,  # 使用可见浏览器，不易被检测
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
                "viewport": {"width": 1280, "height": 800},
                "ignore_default_args": ["--enable-automation"],
            }

            # 如果找到本地 Chrome，使用它
            if chrome_path:
                launch_options["executable_path"] = chrome_path

            context = await p.chromium.launch_persistent_context(**launch_options)

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 注入反检测脚本
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                    window.chrome = { runtime: {} };
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
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)

                # 等待视频信息被捕获
                try:
                    await asyncio.wait_for(video_info_captured.wait(), timeout=20)
                except asyncio.TimeoutError:
                    pass

                # 如果没捕获到，尝试从页面提取
                if not video_data:
                    await page.wait_for_timeout(3000)
                    video_data = await self._extract_from_page(page)

            finally:
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
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions",
                ],
                "viewport": {"width": 1280, "height": 800},
                "ignore_default_args": ["--enable-automation"],
            }

            if chrome_path:
                launch_options["executable_path"] = chrome_path

            context = await p.chromium.launch_persistent_context(**launch_options)

            try:
                page = context.pages[0] if context.pages else await context.new_page()

                # 注入反检测脚本
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                    window.chrome = { runtime: {} };
                """)

                # 访问用户主页
                await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(3000)

                if interactive:
                    # 等待用户手动完成验证
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(
                        None,
                        lambda: input("\n>>> 浏览器已打开，如需完成验证请在浏览器中操作，完成后回到此处按 回车键 继续...\n")
                    )
                    await page.wait_for_timeout(2000)
                else:
                    # API模式：等待页面稳定后，用 wait_for_selector 等视频列表出现
                    # （Playwright 的 wait_for_selector 能跨导航自动重试）
                    try:
                        await page.wait_for_load_state("networkidle", timeout=30000)
                    except Exception:
                        pass
                    try:
                        await page.wait_for_selector(
                            'div[class*="userNewUi"]',
                            timeout=120000,
                        )
                    except Exception:
                        pass
                    # 额外等待确保内容渲染完成
                    await page.wait_for_timeout(3000)

                # 提取链接的JS脚本（排除 user-page-footer 推荐区）
                extract_js = '''() => {
                    const containers = document.querySelectorAll('div[class*="userNewUi"]');
                    const links = new Set();
                    containers.forEach(container => {
                        const aTags = container.querySelectorAll('a[href]');
                        aTags.forEach(a => {
                            if (a.closest('.user-page-footer')) return;
                            const href = a.getAttribute('href');
                            if (href) links.add(href);
                        });
                    });
                    return Array.from(links);
                }'''

                # 安全执行 evaluate（跨导航时可能失败）
                async def safe_evaluate(js: str, default=None):
                    try:
                        return await page.evaluate(js)
                    except Exception:
                        await page.wait_for_timeout(1000)
                        try:
                            return await page.evaluate(js)
                        except Exception:
                            return default if default is not None else []

                # 滚动加载所有视频
                prev_count = 0
                no_change_rounds = 0

                for i in range(max_scroll):
                    hrefs = await safe_evaluate(extract_js)

                    current_count = len(hrefs)
                    if current_count == prev_count:
                        no_change_rounds += 1
                        if no_change_rounds >= 3:
                            break
                    else:
                        no_change_rounds = 0
                    prev_count = current_count

                    # 向下滚动
                    await safe_evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await page.wait_for_timeout(2000)

                # 最终提取一次
                hrefs = await safe_evaluate(extract_js)

                # 将相对路径转换为完整URL，只保留视频链接
                for href in hrefs:
                    if href.startswith('/video/'):
                        full_url = f"https://www.douyin.com{href}"
                        video_urls.append(full_url)
                    elif 'douyin.com/video/' in href:
                        video_urls.append(href)

            finally:
                await context.close()

        return video_urls

    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载音频"""
        return await self.download(url, output_dir, "best", progress_callback)
