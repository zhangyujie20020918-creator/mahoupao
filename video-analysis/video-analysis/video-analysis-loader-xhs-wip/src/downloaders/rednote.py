"""
小红书 (RedNote) 下载器 - Playwright 版本
通过浏览器渲染页面并拦截视频网络请求获取真实下载地址
"""

import asyncio
import os
import re
import time
from pathlib import Path
from typing import Optional

import aiohttp

from src.core.models import Platform, VideoInfo, DownloadResult, DownloadProgress
from src.core.interfaces import IProgressCallback
from src.core.exceptions import VideoNotFoundError, DownloadFailedError, DownloaderError
from src.config import get_settings
from src.services.browser_manager import BrowserManager
from .base import BaseDownloader


class RedNoteDownloader(BaseDownloader):
    """小红书视频下载器 - 使用 Playwright 拦截视频请求"""

    # 独立 profile 目录，与抖音隔离
    PROFILE_DIR = Path(os.path.expandvars(r"%LocalAppData%\video-analysis\xhs-profile"))

    # XHS 视频 CDN URL 特征（仅匹配视频域名，不含 fe-static/sns-webpic 等静态资源）
    VIDEO_CDN_PATTERNS = [
        "sns-video",
        "xhs-video",
    ]

    @property
    def platform(self) -> Platform:
        return Platform.REDNOTE

    @property
    def supported_domains(self) -> list[str]:
        return [
            "xiaohongshu.com",
            "xhslink.com",
            "xhs.cn",
        ]

    def _is_video_response(self, url: str, content_type: str = "") -> bool:
        """判断是否为视频资源响应"""
        if "video" in content_type:
            return True
        url_lower = url.lower()
        return any(p in url_lower for p in self.VIDEO_CDN_PATTERNS)

    async def _resolve_short_url(self, url: str) -> str:
        """解析短链接到完整 URL"""
        if "xhslink.com" in url or "xhs.cn" in url:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True) as response:
                    return str(response.url)
        return url

    def _extract_note_id(self, url: str) -> Optional[str]:
        """从 URL 提取笔记 ID"""
        patterns = [
            r"/explore/([a-f0-9]+)",
            r"/discovery/item/([a-f0-9]+)",
            r"noteId=([a-f0-9]+)",
            r"/note/([a-f0-9]+)",
        ]
        for pattern in patterns:
            if match := re.search(pattern, url):
                return match.group(1)
        return None

    async def _get_video_url_via_browser(self, url: str) -> tuple[Optional[str], dict]:
        """
        用 Playwright 打开页面，拦截视频 CDN 请求，返回视频 URL 和页面元数据。

        Returns:
            (video_url, meta) — meta 包含 title、author
        """
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)

        browser_manager = await BrowserManager.get_instance()
        page = await browser_manager.get_page(self.PROFILE_DIR)

        video_url: Optional[str] = None
        meta: dict = {"title": None, "author": None}

        # 拦截网络响应，捕获视频 CDN 地址
        async def handle_response(response):
            nonlocal video_url
            if video_url:
                return
            content_type = response.headers.get("content-type", "")
            if self._is_video_response(response.url, content_type):
                video_url = response.url

        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # 等待视频元素出现（最多 15 秒；图片笔记无视频元素会超时跳过）
            try:
                await page.wait_for_selector("video", timeout=15000)
            except Exception:
                pass

            # 从 DOM 提取标题和作者
            try:
                title_el = await page.query_selector(
                    "h1.title, .note-content .title, #detail-title"
                )
                if title_el:
                    meta["title"] = (await title_el.inner_text()).strip()

                author_el = await page.query_selector(
                    ".author-wrapper .username, .user-name"
                )
                if author_el:
                    meta["author"] = (await author_el.inner_text()).strip()
            except Exception:
                pass

            # 网络拦截未命中时，尝试直接读取 <video src="...">
            if not video_url:
                try:
                    video_el = await page.query_selector("video")
                    if video_el:
                        src = await video_el.get_attribute("src")
                        if src and src.startswith("http"):
                            video_url = src
                except Exception:
                    pass

            # 给延迟加载的视频请求额外等待时间
            if not video_url:
                await asyncio.sleep(3)

        finally:
            page.remove_listener("response", handle_response)

        return video_url, meta

    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息（不下载）"""
        resolved_url = await self._resolve_short_url(url)
        note_id = self._extract_note_id(resolved_url)

        if not note_id:
            raise VideoNotFoundError(url, "无法解析笔记 ID")

        _, meta = await self._get_video_url_via_browser(resolved_url)

        return VideoInfo(
            url=resolved_url,
            platform=Platform.REDNOTE,
            video_id=note_id,
            title=meta.get("title") or f"小红书笔记_{note_id}",
            author=meta.get("author"),
        )

    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载视频"""
        start_time = time.time()

        resolved_url = await self._resolve_short_url(url)
        note_id = self._extract_note_id(resolved_url)

        if not note_id:
            raise VideoNotFoundError(url, "无法解析笔记 ID")

        video_url, meta = await self._get_video_url_via_browser(resolved_url)

        if not video_url:
            raise DownloadFailedError(
                url,
                "未能捕获到视频地址，请确认链接为视频笔记，且浏览器已完成登录"
            )

        title = meta.get("title") or f"小红书笔记_{note_id}"
        video_info = VideoInfo(
            url=resolved_url,
            platform=Platform.REDNOTE,
            video_id=note_id,
            title=title,
            author=meta.get("author"),
        )

        if progress_callback:
            progress_callback.on_start(video_info)

        # 清理文件名
        safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:100]
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{safe_title}.mp4"

        # 流式下载视频文件
        # XHS CDN 需要 Range 头才会返回完整内容，不带 Range 只返回小片段
        async with aiohttp.ClientSession() as session:
            headers = {
                "Referer": "https://www.xiaohongshu.com/",
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Range": "bytes=0-",
            }
            async with session.get(video_url, headers=headers) as response:
                if response.status not in (200, 206):
                    raise DownloadFailedError(url, f"下载失败: HTTP {response.status}")

                total_size = int(response.headers.get("Content-Length", 0))
                downloaded = 0

                with open(output_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)

                        if progress_callback and total_size > 0:
                            progress = DownloadProgress(
                                status="downloading",
                                percentage=downloaded / total_size * 100,
                                downloaded_bytes=downloaded,
                                total_bytes=total_size,
                            )
                            progress_callback.on_progress(progress)

        file_size = output_path.stat().st_size
        result = DownloadResult(
            success=True,
            video_info=video_info,
            file_path=output_path,
            file_size=file_size,
            elapsed_time=time.time() - start_time,
        )

        if progress_callback:
            progress_callback.on_complete(result)

        return result

    # ─────────────────────────────────────────────
    # 用户主页批量下载
    # ─────────────────────────────────────────────

    @staticmethod
    def is_user_profile_url(url: str) -> bool:
        """判断是否为小红书用户主页 URL"""
        return "/user/profile/" in url

    async def extract_user_video_urls(
        self,
        user_url: str,
        max_scroll: int = 30,
        video_only: bool = True,
    ) -> tuple[list[str], str]:
        """
        从小红书用户主页提取所有视频笔记链接。

        通过拦截 /api/sns/web/v1/user_posted API 响应获取笔记 ID 和 xsec_token，
        构造带 token 的完整 URL 避免 404。

        复用 BrowserManager 的浏览器实例，在新 Page 中完成提取后关闭该 Page，
        避免与 BrowserManager 的 persistent context 产生 Profile 锁冲突。

        Args:
            video_only: True 时只提取 type==video 的笔记（默认），False 提取全部

        Returns:
            (url_list, username)
        """
        self.PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        # note_id -> {"url": str, "type": str}
        collected: dict[str, dict] = {}
        username = ""

        # 复用 BrowserManager 已持有的 persistent context，避免 Profile 重复锁定
        browser_manager = await BrowserManager.get_instance()
        # 确保浏览器用正确的 Profile 启动
        await browser_manager.get_page(self.PROFILE_DIR)
        context = browser_manager._context

        # 创建专用提取页面，不影响 BrowserManager 的主页面
        extraction_page = await context.new_page()

        try:
            async def handle_api_response(response):
                nonlocal username
                if "user_posted" not in response.url:
                    return
                try:
                    body = await response.json()
                    notes = body.get("data", {}).get("notes", [])
                    for note in notes:
                        note_id = note.get("note_id", "")
                        xsec_token = note.get("xsec_token", "")
                        note_type = note.get("type", "")
                        if not note_id or not xsec_token:
                            continue
                        url = (
                            f"https://www.xiaohongshu.com/explore/{note_id}"
                            f"?xsec_token={xsec_token}&xsec_source=pc_user"
                        )
                        collected[note_id] = {"url": url, "type": note_type}
                    print(f"[小红书] API 响应: +{len(notes)} 条，累计 {len(collected)} 条")
                except Exception:
                    pass

            extraction_page.on("response", handle_api_response)

            print(f"[小红书] 正在打开用户主页: {user_url}")
            await extraction_page.goto(user_url, wait_until="domcontentloaded", timeout=30000)

            # 等待笔记列表容器出现
            try:
                await extraction_page.wait_for_selector(
                    "section.note-item, .feeds-container, .user-posted-works",
                    timeout=15000,
                )
            except Exception:
                print("[小红书] 未检测到笔记列表，继续尝试...")

            await asyncio.sleep(2)

            # 获取用户名
            try:
                el = await extraction_page.query_selector(".user-name, .username, h1.name")
                if el:
                    username = (await el.inner_text()).strip()
            except Exception:
                pass

            no_new_rounds = 0

            for i in range(max_scroll):
                prev_count = len(collected)
                # 滚动到页面底部触发加载更多 API 请求
                await extraction_page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1.5)

                new_count = len(collected)
                print(f"[小红书] 滚动 {i+1}/{max_scroll}，已收集 {new_count} 条")

                if new_count == prev_count:
                    no_new_rounds += 1
                    if no_new_rounds >= 3:
                        print("[小红书] 连续 3 次无新内容，认为已到底部")
                        break
                    await asyncio.sleep(2)
                else:
                    no_new_rounds = 0

            extraction_page.remove_listener("response", handle_api_response)
        finally:
            await extraction_page.close()

        # 按需过滤视频类型
        if video_only:
            video_items = {k: v for k, v in collected.items() if v["type"] == "video"}
            skipped = len(collected) - len(video_items)
            if skipped:
                print(f"[小红书] 过滤掉 {skipped} 条图片笔记，保留 {len(video_items)} 条视频")
            collected = video_items

        url_list = [v["url"] for v in collected.values()]
        print(f"[小红书] 共收集到 {len(url_list)} 条视频笔记链接")
        return url_list, username
