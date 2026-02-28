"""
下载服务 - 高层业务逻辑封装
提供统一的下载接口，隐藏底层复杂性
"""

import asyncio
import time
import json
import re
import random
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Any
from datetime import datetime

from src.core.interfaces import IDownloader, IDownloadService, IProgressCallback
from src.core.models import VideoInfo, DownloadResult, Platform
from src.core.exceptions import UnsupportedPlatformError, DownloaderError
from src.config import get_settings
from .factory import DownloaderFactory
from .progress_handler import SilentProgressHandler
from .browser_manager import get_browser_manager


class DownloadService(IDownloadService):
    """
    下载服务

    提供简洁的API进行视频下载，自动处理:
    - 平台识别与下载器选择
    - 进度显示
    - 错误处理
    - 批量下载

    使用示例:
        service = DownloadService()
        result = await service.download("https://youtube.com/watch?v=xxx")
    """

    def __init__(self, factory: Optional[DownloaderFactory] = None):
        self._factory = factory or DownloaderFactory()
        self._settings = get_settings()

    def register_downloader(self, downloader: IDownloader) -> None:
        """注册自定义下载器"""
        self._factory.register(downloader.platform, type(downloader))

    async def download(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        quality: str = "best",
        audio_only: bool = False,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        output_dir = output_dir or self._settings.download.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        downloader = self._factory.get_downloader_for_url(url)

        if audio_only:
            return await downloader.download_audio_only(url, output_dir, progress_callback)
        else:
            return await downloader.download(url, output_dir, quality, progress_callback)

    async def get_info(self, url: str) -> VideoInfo:
        downloader = self._factory.get_downloader_for_url(url)
        return await downloader.get_video_info(url)

    async def batch_download(
        self,
        urls: list[str],
        output_dir: Optional[Path] = None,
        quality: str = "best",
        max_concurrent: int = 3,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> list[DownloadResult]:
        output_dir = output_dir or self._settings.download.output_dir
        callback = progress_callback or SilentProgressHandler()

        semaphore = asyncio.Semaphore(max_concurrent)

        async def download_with_limit(url: str) -> DownloadResult:
            async with semaphore:
                try:
                    return await self.download(url, output_dir, quality, False, callback)
                except Exception as e:
                    platform = Platform.from_url(url)
                    return DownloadResult(
                        success=False,
                        video_info=VideoInfo(url=url, platform=platform, video_id="", title="下载失败"),
                        error_message=str(e),
                    )

        tasks = [download_with_limit(url) for url in urls]
        return await asyncio.gather(*tasks)

    async def download_user_videos(
        self,
        user_url: str,
        output_dir: Optional[Path] = None,
        quality: str = "best",
    ) -> list[DownloadResult]:
        from src.downloaders.douyin import DouyinDownloader

        output_dir = output_dir or self._settings.download.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, DouyinDownloader):
            raise DownloaderError(url=user_url, message="用户主页下载仅支持抖音平台")

        results: list[DownloadResult] = []
        async for event in self.download_user_videos_stream(user_url, output_dir, quality):
            if event.get("type") == "downloaded":
                success = event.get("success", False)
                file_path = Path(event["file_path"]) if event.get("file_path") else None
                file_size = file_path.stat().st_size if file_path and file_path.exists() else None

                results.append(DownloadResult(
                    success=success,
                    video_info=VideoInfo(
                        url=event.get("url", user_url),
                        platform=Platform.DOUYIN,
                        video_id="",
                        title=event.get("title", ""),
                    ),
                    file_path=file_path,
                    file_size=file_size,
                    error_message=event.get("error") if not success else None,
                ))
            elif event.get("type") == "error":
                raise DownloaderError(url=user_url, message=event.get("message", "下载失败"))

        if not results:
            raise DownloaderError(url=user_url, message="未能下载任何视频")

        return results

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
        from src.downloaders.douyin import DouyinDownloader
        import httpx

        start_time = time.time()

        # ========== 反爬配置 ==========
        SCROLL_DELAY = (1.0, 2.0)
        SCROLL_RETRY_DELAY = (5.0, 8.0)  # 无新内容时的重试等待
        PAGE_LOAD_DELAY = (1.5, 2.5)
        VIDEO_INTERVAL = (0.8, 1.8)
        DOWNLOAD_INTERVAL = (0.3, 1.0)

        def random_delay(delay_range: tuple) -> int:
            return int(random.uniform(delay_range[0], delay_range[1]) * 1000)

        USER_AGENTS = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]

        def get_random_ua() -> str:
            return random.choice(USER_AGENTS)

        def format_size(size: int) -> str:
            if size < 1024:
                return f"{size} B"
            elif size < 1024 * 1024:
                return f"{size / 1024:.1f} KB"
            elif size < 1024 * 1024 * 1024:
                return f"{size / (1024 * 1024):.1f} MB"
            else:
                return f"{size / (1024 * 1024 * 1024):.2f} GB"

        async def download_file_http(download_url: str, file_path: Path) -> tuple[bool, int, str]:
            """用 HTTP 下载视频文件"""
            headers = {
                "User-Agent": get_random_ua(),
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
                                    print(f"\r[下载进度] {pct:.1f}% ({format_size(downloaded)}/{format_size(total_size)})", end="", flush=True)
                        print()
                        return True, file_path.stat().st_size, ""
            except Exception as e:
                return False, 0, str(e)

        async def download_subtitle(aweme_detail: dict, srt_path: Path) -> bool:
            """从 aweme_detail 中提取字幕并保存为 SRT 文件"""
            # 抖音字幕在 video_subtitle 或 caption_infos 字段
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
                    "User-Agent": get_random_ua(),
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

        print(f"\n{'='*60}")
        print(f"[用户主页下载] 开始处理: {user_url}")
        print(f"{'='*60}\n")

        yield {"type": "extracting", "message": "正在启动浏览器..."}

        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, DouyinDownloader):
            yield {"type": "error", "message": "用户主页下载仅支持抖音平台"}
            return

        # ========== 初始化浏览器（使用全局管理器保持打开） ==========
        downloader._sync_native_profile()
        chrome_path = downloader._get_chrome_path()

        browser_manager = await get_browser_manager()
        page = await browser_manager.get_page(downloader.PROFILE_DIR, chrome_path)

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
        max_retry_rounds = 3

        try:
            # ========== 验证码/登录检测函数 ==========
            async def check_captcha() -> tuple[bool, str]:
                checks = [
                    ('div[class*="login-panel"]', '登录弹窗'),
                    ('div[class*="loginContainer"]', '登录弹窗'),
                    ('div[class*="login-guide"]', '登录弹窗'),
                    ('div.login-mask', '登录弹窗'),
                    ('div.captcha_verify_container', '滑块验证码'),
                    ('div[class*="captcha-verify"]', '滑块验证码'),
                    ('div#captcha_container', '验证码'),
                    ('div.verify-captcha-container', '图片验证码'),
                    ('div[class*="secsdk-captcha"]', '安全验证码'),
                    ('div[class*="captcha"]', '验证码'),
                    ('iframe[src*="captcha"]', '验证码'),
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

            async def wait_for_auth_resolved(max_wait: int = 120) -> bool:
                start = time.time()
                last_type = ""
                while time.time() - start < max_wait:
                    has_block, block_type = await check_captcha()
                    if not has_block:
                        return True
                    if block_type != last_type:
                        print(f"[等待] ⏳ 等待用户完成: {block_type}")
                        last_type = block_type
                    await page.wait_for_timeout(1000)
                return False

            async def check_login_status() -> bool:
                try:
                    # 检测中文/英文登录按钮
                    login_btn = await page.query_selector(
                        'button:has-text("登录"), a:has-text("登录"), '
                        'button:has-text("Login"), a:has-text("Login"), '
                        'div[class*="login-btn"], button[class*="login"], '
                        'div[class*="login-guide"]'
                    )
                    if login_btn and await login_btn.is_visible():
                        return False
                    # 检测头像（已登录标志）
                    avatar = await page.query_selector(
                        'img[class*="avatar"], div[class*="avatar"], '
                        'img[class*="Avatar"], div[class*="Avatar"]'
                    )
                    if avatar and await avatar.is_visible():
                        return True
                    # 既没有登录按钮也没有头像时，默认视为已登录
                    # 避免选择器不匹配时误报未登录
                    return True
                except Exception:
                    return True

            async def save_debug_info(reason: str = "unknown"):
                timestamp = int(time.time())
                debug_dir = downloader.LOG_DIR
                debug_dir.mkdir(parents=True, exist_ok=True)
                try:
                    await page.screenshot(path=str(debug_dir / f"debug_{reason}_{timestamp}.png"))
                except Exception:
                    pass
                try:
                    content = await page.content()
                    with open(debug_dir / f"debug_{reason}_{timestamp}.html", "w", encoding="utf-8") as f:
                        f.write(content)
                except Exception:
                    pass

            async def extract_username() -> str:
                """提取用户名"""
                try:
                    # 尝试从页面标题提取
                    title = await page.title()
                    if title and "抖音" in title:
                        name = title.replace("的主页 - 抖音", "").replace("的抖音", "").strip()
                        if name:
                            return name
                    # 尝试从页面元素提取
                    name_el = await page.query_selector('h1[class*="name"], span[class*="nickname"], [data-e2e="user-info-nickname"]')
                    if name_el:
                        name = await name_el.text_content()
                        if name:
                            return name.strip()
                except Exception:
                    pass
                return ""

            def get_existing_videos(folder: Path) -> set[str]:
                """获取文件夹中已存在的视频（通过读取元数据）"""
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

            def save_metadata(folder: Path, user_info: dict, videos: list[dict]):
                """保存元数据到文件夹"""
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

                # 同时保存URL列表文件
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

            # ========== 第一步：访问用户主页 ==========
            print(f"[步骤1] 正在访问用户主页...")
            yield {"type": "extracting", "message": "正在访问用户主页，提取视频列表..."}

            await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(random_delay(PAGE_LOAD_DELAY))

            # 循环检测验证码/登录
            for auth_attempt in range(10):
                has_block, block_type = await check_captcha()
                if not has_block:
                    if auth_attempt > 0:
                        print(f"[信息] ✓ 验证/登录已全部完成")
                    break
                print(f"[警告] ⚠️ 检测到 {block_type}！请在浏览器中完成... (第{auth_attempt+1}次)")
                yield {"type": "extracting", "message": f"检测到{block_type}，请在浏览器中完成验证..."}
                resolved = await wait_for_auth_resolved(120)
                if not resolved:
                    await save_debug_info("auth_timeout")
                    yield {"type": "error", "message": f"验证码/登录超时未完成"}
                    return
                print(f"[信息] ✓ {block_type} 已通过")
                await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))
            else:
                await save_debug_info("max_auth_retries")
                yield {"type": "error", "message": "验证/登录重试次数过多"}
                return

            # 等待视频链接
            video_links_found = False
            for load_attempt in range(5):
                print(f"[步骤1] 等待页面加载... (第{load_attempt+1}次)")
                try:
                    await page.wait_for_load_state("networkidle", timeout=30000)
                except Exception:
                    pass

                has_block, block_type = await check_captcha()
                if has_block:
                    print(f"[警告] ⚠️ 检测到 {block_type}！请在浏览器中完成...")
                    resolved = await wait_for_auth_resolved(120)
                    if not resolved:
                        yield {"type": "error", "message": f"验证码/登录超时未完成"}
                        return
                    await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))
                    continue

                try:
                    await page.wait_for_selector('a[href*="/video/"]', timeout=15000)
                    print(f"[步骤1] ✓ 视频链接已加载")
                    is_logged_in = await check_login_status()
                    if not is_logged_in:
                        print(f"[警告] ⚠️ 抖音未登录！未登录状态下可能无法获取全部视频")
                        yield {"type": "extracting", "message": "⚠️ 未登录抖音，可能无法获取全部视频。建议登录后重试。"}
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
                    await save_debug_info("no_videos_after_refresh")
                    yield {"type": "error", "message": "无法加载视频列表，请检查网络或重新登录"}
                    return

            # ========== 提取用户名并创建文件夹 ==========
            username = await extract_username()
            if username:
                safe_username = re.sub(r'[\\/*?:"<>|]', "_", username).strip("_")[:50]
                user_folder = output_dir / safe_username
            else:
                user_folder = output_dir / f"douyin_user_{int(time.time())}"

            user_folder.mkdir(parents=True, exist_ok=True)
            print(f"[用户主页下载] 用户名: {username or '未知'}")
            print(f"[用户主页下载] 保存目录: {user_folder}")

            # 加载已下载的视频URL
            downloaded_urls = get_existing_videos(user_folder)
            if downloaded_urls:
                print(f"[信息] 发现 {len(downloaded_urls)} 个已下载的视频，将跳过")

            await page.wait_for_timeout(random_delay(PAGE_LOAD_DELAY))

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
            await save_debug_info("before_scroll")
            try:
                scroll_debug = await page.evaluate('''() => {
                    const results = [];
                    // 检查哪些元素可以滚动
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
                    await page.wait_for_timeout(random_delay((0.8, 1.5)))
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
                    await page.wait_for_timeout(random_delay(SCROLL_RETRY_DELAY))
                    continue
                prev_count = current_count

                # 模拟真实用户滚动 - 先将鼠标移到页面中央，再触发 wheel 事件
                await page.mouse.move(random.randint(900, 1100), random.randint(550, 700))
                delta_y = random.randint(600, 1800)
                await page.mouse.wheel(0, delta_y)

                await page.wait_for_timeout(random_delay(SCROLL_DELAY))

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
                await save_debug_info("no_videos")
                yield {"type": "error", "message": "未找到任何视频，可能需要登录或完成验证"}
                return

            yield {
                "type": "extracted",
                "total": video_count,
                "work_count": work_count,
                "non_video_count": non_video_count,
                "message": f"找到 {video_count} 个视频（作品 {work_count} 个），开始下载...",
            }

            # ========== 第二步：逐个下载视频 ==========
            print(f"\n[步骤2] 开始下载视频...")
            downloaded_videos_info: list[dict] = []

            for idx, video_url in enumerate(video_urls, 1):
                # 检查是否已下载
                if video_url in downloaded_urls:
                    skipped_count += 1
                    print(f"[视频 {idx}/{video_count}] 已存在，跳过")
                    downloaded_videos_info.append({"url": video_url, "title": "", "success": True, "skipped": True})
                    yield {
                        "type": "downloaded",
                        "index": idx,
                        "total": video_count,
                        "title": "(已存在)",
                        "success": True,
                        "skipped": True,
                        "succeeded_so_far": succeeded_count,
                        "skipped_count": skipped_count,
                    }
                    continue

                print(f"\n{'─'*50}")
                print(f"[视频 {idx}/{video_count}] {video_url}")

                yield {
                    "type": "downloading",
                    "index": idx,
                    "total": video_count,
                    "url": video_url,
                    "title": f"视频 {idx}",
                    "succeeded_so_far": succeeded_count,
                    "remaining": video_count - succeeded_count - len(failed_list) - skipped_count,
                }

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
                    await page.wait_for_timeout(random_delay((1.0, 2.0)))

                    has_block, block_type = await check_captcha()
                    if has_block:
                        print(f"[视频 {idx}/{video_count}] ⚠️ 检测到 {block_type}！")
                        resolved = await wait_for_auth_resolved(120)
                        if not resolved:
                            failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": "验证超时"})
                            yield {"type": "downloaded", "index": idx, "total": video_count, "title": f"视频 {idx}", "success": False, "error": "验证码超时", "permanently_failed": True}
                            page.remove_listener("response", handle_response)
                            continue
                        await page.wait_for_timeout(int(random.uniform(10, 12) * 1000))

                    try:
                        await asyncio.wait_for(video_captured.wait(), timeout=15)
                    except asyncio.TimeoutError:
                        print(f"[视频 {idx}/{video_count}] 获取超时，尝试从页面提取...")

                    page.remove_listener("response", handle_response)

                    if not video_data:
                        video_data = await downloader._extract_from_page(page)

                    if not video_data:
                        print(f"[视频 {idx}/{video_count}] ✗ 无法获取视频信息")
                        failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": "无法获取视频信息"})
                        yield {"type": "downloaded", "index": idx, "total": video_count, "title": f"视频 {idx}", "success": False, "error": "无法获取视频信息", "permanently_failed": True}
                        continue

                    title = video_data.get("desc", f"视频 {idx}") or f"视频 {idx}"
                    video = video_data.get("video", {})

                    # 提取下载地址
                    download_url = None
                    play_addr = video.get("play_addr", {})
                    url_list = play_addr.get("url_list", [])
                    if url_list:
                        download_url = url_list[0].replace("playwm", "play")

                    if not download_url:
                        bit_rate = video.get("bit_rate", [])
                        if bit_rate:
                            sorted_rates = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
                            play_addr = sorted_rates[0].get("play_addr", {})
                            url_list = play_addr.get("url_list", [])
                            if url_list:
                                download_url = url_list[0]

                    if not download_url:
                        print(f"[视频 {idx}/{video_count}] ✗ 无法获取下载地址")
                        failed_list.append({"url": video_url, "title": title, "error": "无法获取下载地址"})
                        yield {"type": "downloaded", "index": idx, "total": video_count, "title": title, "success": False, "error": "无法获取下载地址", "permanently_failed": True}
                        continue

                    # 从URL提取视频ID，用于文件名去重
                    video_id_match = re.search(r'/video/(\d+)', video_url)
                    video_id = video_id_match.group(1)[-8:] if video_id_match else ""

                    # 检查文件是否已存在
                    safe_title = re.sub(r'[\s\\/*?:"<>|]', "_", title).strip("_")[:80]
                    if not safe_title.strip():
                        safe_title = f"douyin_{idx}"
                    # 文件名加上视频ID后缀，避免同名视频冲突
                    filename = f"{safe_title}_{video_id}.mp4" if video_id else f"{safe_title}.mp4"
                    file_path = user_folder / filename

                    # 兼容旧文件名（无ID后缀）
                    old_file_path = user_folder / f"{safe_title}.mp4"

                    if file_path.exists() or (old_file_path.exists() and old_file_path != file_path):
                        existing = file_path if file_path.exists() else old_file_path
                        print(f"[视频 {idx}/{video_count}] 文件已存在，跳过: {existing.name}")
                        skipped_count += 1
                        downloaded_urls.add(video_url)
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "skipped": True, "file_path": str(existing)})
                        yield {"type": "downloaded", "index": idx, "total": video_count, "title": title, "success": True, "skipped": True, "file_path": str(existing)}
                        continue

                    print(f"[视频 {idx}/{video_count}] 正在下载: {title[:30]}...")
                    success, file_size, error_msg = await download_file_http(download_url, file_path)

                    if success:
                        succeeded_count += 1
                        downloaded_urls.add(video_url)
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "file_path": str(file_path)})
                        print(f"[视频 {idx}/{video_count}] ✓ 下载成功: {format_size(file_size)}")

                        # 尝试提取字幕
                        srt_path = file_path.with_suffix(".srt")
                        has_subtitle = await download_subtitle(video_data, srt_path)
                        if has_subtitle:
                            print(f"[视频 {idx}/{video_count}] ✓ 字幕已保存: {srt_path.name}")

                        yield {
                            "type": "downloaded",
                            "index": idx,
                            "total": video_count,
                            "title": title,
                            "success": True,
                            "file_path": str(file_path),
                            "file_size_human": format_size(file_size),
                            "has_subtitle": has_subtitle,
                            "succeeded_so_far": succeeded_count,
                            "remaining": video_count - succeeded_count - len(failed_list) - skipped_count,
                        }
                        await asyncio.sleep(random_delay(DOWNLOAD_INTERVAL) / 1000)
                    else:
                        print(f"[视频 {idx}/{video_count}] ✗ 下载失败: {error_msg}")
                        failed_list.append({"url": video_url, "title": title, "error": error_msg})
                        downloaded_videos_info.append({"url": video_url, "title": title, "success": False, "error": error_msg})
                        yield {"type": "downloaded", "index": idx, "total": video_count, "title": title, "success": False, "error": error_msg, "permanently_failed": True}

                except Exception as e:
                    print(f"[视频 {idx}/{video_count}] ✗ 异常: {str(e)}")
                    page.remove_listener("response", handle_response)
                    failed_list.append({"url": video_url, "title": f"视频 {idx}", "error": str(e)})
                    yield {"type": "downloaded", "index": idx, "total": video_count, "title": f"视频 {idx}", "success": False, "error": str(e), "permanently_failed": True}

                await page.wait_for_timeout(random_delay(VIDEO_INTERVAL))

            # ========== 第三步：失败视频重试 ==========
            retry_round = 0
            while failed_list and retry_round < max_retry_rounds:
                retry_round += 1
                failed_urls = [f["url"] for f in failed_list]
                retry_count = len(failed_urls)

                print(f"\n{'='*60}")
                print(f"[重试 第{retry_round}/{max_retry_rounds}轮] 有 {retry_count} 个视频下载失败，准备重试...")
                print(f"{'='*60}")

                yield {
                    "type": "retrying",
                    "round": retry_round,
                    "max_rounds": max_retry_rounds,
                    "failed_count": retry_count,
                    "message": f"开始第 {retry_round} 轮重试，共 {retry_count} 个失败视频...",
                }

                # 回到用户首页重新获取链接
                print(f"[重试] 回到用户首页重新获取视频链接...")
                await page.goto(user_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(random_delay(PAGE_LOAD_DELAY))

                # 检查验证码
                has_block, block_type = await check_captcha()
                if has_block:
                    print(f"[重试] ⚠️ 检测到 {block_type}！请在浏览器中完成...")
                    resolved = await wait_for_auth_resolved(120)
                    if not resolved:
                        print(f"[重试] 验证超时，跳过本轮重试")
                        break
                    await page.wait_for_timeout(int(random.uniform(5, 8) * 1000))

                # 等待页面加载
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
                    await page.wait_for_timeout(random_delay(SCROLL_DELAY))
                    hrefs = await page.evaluate(extract_js)
                    if work_count and len(hrefs) >= work_count:
                        break

                # 清空失败列表，准备重新记录
                old_failed_list = failed_list.copy()
                failed_list.clear()

                # 重新下载失败的视频
                for idx, failed_item in enumerate(old_failed_list, 1):
                    video_url = failed_item["url"]

                    print(f"\n{'─'*50}")
                    print(f"[重试 {idx}/{retry_count}] {video_url}")

                    yield {
                        "type": "downloading",
                        "index": idx,
                        "total": retry_count,
                        "url": video_url,
                        "title": failed_item.get("title", f"视频 {idx}"),
                        "is_retry": True,
                        "retry_round": retry_round,
                    }

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
                        await page.wait_for_timeout(random_delay((1.5, 2.5)))

                        # 检查验证码
                        has_block, block_type = await check_captcha()
                        if has_block:
                            print(f"[重试 {idx}/{retry_count}] ⚠️ 检测到 {block_type}！")
                            resolved = await wait_for_auth_resolved(120)
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
                            video_data = await downloader._extract_from_page(page)

                        if not video_data:
                            print(f"[重试 {idx}/{retry_count}] ✗ 仍无法获取视频信息")
                            failed_list.append(failed_item)
                            continue

                        title = video_data.get("desc", failed_item.get("title", f"视频 {idx}")) or f"视频 {idx}"
                        video = video_data.get("video", {})

                        # 提取下载地址
                        download_url = None
                        play_addr = video.get("play_addr", {})
                        url_list = play_addr.get("url_list", [])
                        if url_list:
                            download_url = url_list[0].replace("playwm", "play")

                        if not download_url:
                            bit_rate = video.get("bit_rate", [])
                            if bit_rate:
                                sorted_rates = sorted(bit_rate, key=lambda x: x.get("bit_rate", 0), reverse=True)
                                play_addr = sorted_rates[0].get("play_addr", {})
                                url_list = play_addr.get("url_list", [])
                                if url_list:
                                    download_url = url_list[0]

                        if not download_url:
                            print(f"[重试 {idx}/{retry_count}] ✗ 仍无法获取下载地址")
                            failed_list.append({"url": video_url, "title": title, "error": "无法获取下载地址"})
                            continue

                        # 下载
                        safe_title = re.sub(r'[\s\\/*?:"<>|]', "_", title).strip("_")[:80]
                        if not safe_title.strip():
                            safe_title = f"douyin_retry_{idx}"
                        file_path = user_folder / f"{safe_title}.mp4"

                        print(f"[重试 {idx}/{retry_count}] 正在下载: {title[:30]}...")
                        success, file_size, error_msg = await download_file_http(download_url, file_path)

                        if success:
                            succeeded_count += 1
                            downloaded_urls.add(video_url)
                            # 更新 downloaded_videos_info 中对应的记录
                            for v in downloaded_videos_info:
                                if v.get("url") == video_url:
                                    v["success"] = True
                                    v["file_path"] = str(file_path)
                                    v.pop("error", None)
                                    break
                            else:
                                downloaded_videos_info.append({"url": video_url, "title": title, "success": True, "file_path": str(file_path)})

                            print(f"[重试 {idx}/{retry_count}] ✓ 重试成功: {format_size(file_size)}")
                            yield {
                                "type": "downloaded",
                                "index": idx,
                                "total": retry_count,
                                "title": title,
                                "success": True,
                                "file_path": str(file_path),
                                "file_size_human": format_size(file_size),
                                "is_retry": True,
                                "retry_round": retry_round,
                            }
                        else:
                            print(f"[重试 {idx}/{retry_count}] ✗ 重试仍失败: {error_msg}")
                            failed_list.append({"url": video_url, "title": title, "error": error_msg})

                    except Exception as e:
                        print(f"[重试 {idx}/{retry_count}] ✗ 异常: {str(e)}")
                        page.remove_listener("response", handle_response_retry)
                        failed_list.append({"url": video_url, "title": failed_item.get("title", f"视频 {idx}"), "error": str(e)})

                    await page.wait_for_timeout(random_delay(VIDEO_INTERVAL))

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
            save_metadata(user_folder, user_info, downloaded_videos_info)
            print(f"\n[信息] 已保存元数据到: {user_folder}")

            # 浏览器保持打开
            browser_manager.keep_alive()

        except Exception as e:
            print(f"\n[错误] {str(e)}")
            yield {"type": "error", "message": str(e)}
            return

        # ========== 完成 ==========
        elapsed = round(time.time() - start_time, 1)
        print(f"\n{'='*60}")
        print(f"[完成] 作品: {work_count} | 视频: {video_count} | 非视频: {non_video_count}")
        print(f"[完成] 新下载: {succeeded_count} | 已存在跳过: {skipped_count} | 失败: {len(failed_list)}")
        print(f"[完成] 耗时: {elapsed}s")
        print(f"[完成] 保存目录: {user_folder}")
        print(f"{'='*60}\n")

        yield {
            "type": "done",
            "total": video_count,
            "work_count": work_count,
            "non_video_count": non_video_count,
            "succeeded": succeeded_count,
            "skipped": skipped_count,
            "failed": len(failed_list),
            "skipped_videos": failed_list,
            "elapsed_time": elapsed,
            "folder_path": str(user_folder),
            "username": username,
        }

    def get_supported_platforms(self) -> list[str]:
        return [p.name for p in self._factory.get_supported_platforms()]

    def get_supported_domains(self) -> list[str]:
        return self._factory.get_supported_domains()

    def is_url_supported(self, url: str) -> bool:
        try:
            self._factory.get_downloader_for_url(url)
            return True
        except UnsupportedPlatformError:
            return False
