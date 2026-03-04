"""
小红书 (RedNote) 下载器
小红书反爬较严格，需要特殊处理
"""

import json
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote

import aiohttp

from src.core.models import Platform, VideoInfo, DownloadResult
from src.core.interfaces import IProgressCallback
from src.core.exceptions import VideoNotFoundError, DownloadFailedError, DownloaderError
from src.config import get_settings
from .base import BaseDownloader


class RedNoteDownloader(BaseDownloader):
    """小红书视频下载器"""

    def __init__(self):
        super().__init__()
        self._session: Optional[aiohttp.ClientSession] = None

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

    def _get_headers(self) -> dict:
        """获取请求头"""
        settings = get_settings()
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.xiaohongshu.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        }

        if settings.platform.rednote_cookie:
            headers["Cookie"] = settings.platform.rednote_cookie

        return headers

    def _get_extra_options(self) -> dict:
        """小红书特定配置"""
        return {
            "http_headers": self._get_headers(),
            "concurrent_fragment_downloads": 1,
        }

    async def _resolve_short_url(self, url: str) -> str:
        """解析短链接到完整URL"""
        if "xhslink.com" in url or "xhs.cn" in url:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers=self._get_headers(),
                    allow_redirects=True
                ) as response:
                    return str(response.url)
        return url

    def _extract_note_id(self, url: str) -> Optional[str]:
        """从URL提取笔记ID"""
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

    async def _fetch_page_data(self, url: str) -> dict:
        """获取页面数据并解析JSON"""
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._get_headers()) as response:
                if response.status != 200:
                    raise DownloadFailedError(url, f"获取页面失败: HTTP {response.status}")

                html = await response.text()

                # 尝试从页面中提取 __INITIAL_STATE__ 数据
                pattern = r'<script>window\.__INITIAL_STATE__\s*=\s*(.+?)</script>'
                match = re.search(pattern, html, re.DOTALL)

                if match:
                    json_str = match.group(1).strip()
                    # 处理 undefined 值
                    json_str = json_str.replace('undefined', 'null')
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError:
                        pass

                # 备用方案：尝试提取其他格式的数据
                pattern2 = r'"noteDetailMap":\s*(\{.+?\})\s*,'
                match2 = re.search(pattern2, html)
                if match2:
                    try:
                        return {"noteDetailMap": json.loads(match2.group(1))}
                    except json.JSONDecodeError:
                        pass

                raise DownloadFailedError(url, "无法解析页面数据")

    def _extract_video_info_from_data(self, data: dict, url: str, note_id: str) -> dict:
        """从页面数据中提取视频信息"""
        try:
            # 尝试从 noteDetailMap 中获取数据
            note_detail_map = data.get("note", {}).get("noteDetailMap", {})
            if not note_detail_map:
                note_detail_map = data.get("noteDetailMap", {})

            note_data = None
            for key, value in note_detail_map.items():
                if isinstance(value, dict) and "note" in value:
                    note_data = value["note"]
                    break

            if not note_data:
                # 尝试其他路径
                note_data = data.get("note", {}).get("note", {})

            if not note_data:
                return {
                    "video_url": None,
                    "title": f"小红书笔记_{note_id}",
                    "author": None,
                    "cover": None,
                    "type": "unknown"
                }

            # 提取视频信息
            video = note_data.get("video", {})
            video_url = None

            # 尝试获取视频URL
            if video:
                # 优先使用 h264 格式
                for key in ["h264", "h265", "av1"]:
                    streams = video.get("media", {}).get("stream", {}).get(key, [])
                    if streams and isinstance(streams, list) and len(streams) > 0:
                        # 选择最高质量
                        best_stream = max(streams, key=lambda x: x.get("videoBitrate", 0))
                        backup_urls = best_stream.get("backupUrls", [])
                        master_url = best_stream.get("masterUrl", "")
                        video_url = backup_urls[0] if backup_urls else master_url
                        if video_url:
                            break

                # 备用：直接获取视频URL
                if not video_url:
                    video_url = video.get("url") or video.get("originVideoUrl")

            # 提取其他信息
            title = note_data.get("title") or note_data.get("desc", "")[:50] or f"小红书笔记_{note_id}"
            author = note_data.get("user", {}).get("nickname")
            cover = note_data.get("imageList", [{}])[0].get("url") if note_data.get("imageList") else None
            note_type = note_data.get("type", "")

            # 判断是否为图片笔记
            if note_type == "normal" or (not video and note_data.get("imageList")):
                return {
                    "video_url": None,
                    "title": title,
                    "author": author,
                    "cover": cover,
                    "type": "image",
                    "images": [img.get("url") or img.get("urlDefault") for img in note_data.get("imageList", [])]
                }

            return {
                "video_url": video_url,
                "title": title,
                "author": author,
                "cover": cover,
                "type": "video"
            }

        except Exception as e:
            return {
                "video_url": None,
                "title": f"小红书笔记_{note_id}",
                "author": None,
                "cover": None,
                "type": "unknown",
                "error": str(e)
            }

    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息"""
        # 先解析短链接
        resolved_url = await self._resolve_short_url(url)
        note_id = self._extract_note_id(resolved_url)

        if not note_id:
            raise VideoNotFoundError(url, "无法解析笔记ID")

        try:
            # 尝试从页面获取信息
            page_data = await self._fetch_page_data(resolved_url)
            info = self._extract_video_info_from_data(page_data, resolved_url, note_id)

            if info.get("type") == "image":
                raise DownloaderError(url, "此链接为图片笔记，暂不支持下载。请使用视频笔记链接。")

            return VideoInfo(
                url=resolved_url,
                platform=Platform.REDNOTE,
                video_id=note_id,
                title=info.get("title", f"小红书笔记_{note_id}"),
                author=info.get("author"),
                thumbnail=info.get("cover"),
            )
        except DownloaderError:
            raise
        except Exception as e:
            # 返回基本信息
            return VideoInfo(
                url=resolved_url,
                platform=Platform.REDNOTE,
                video_id=note_id,
                title=f"小红书笔记_{note_id}",
                author=None,
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

        # 解析短链接
        resolved_url = await self._resolve_short_url(url)
        note_id = self._extract_note_id(resolved_url)

        if not note_id:
            raise VideoNotFoundError(url, "无法解析笔记ID")

        try:
            # 获取页面数据
            page_data = await self._fetch_page_data(resolved_url)
            info = self._extract_video_info_from_data(page_data, resolved_url, note_id)

            # 检查是否为图片笔记
            if info.get("type") == "image":
                raise DownloaderError(url, "此链接为图片笔记，暂不支持下载。请使用视频笔记链接。")

            video_url = info.get("video_url")

            if not video_url:
                # 尝试使用 yt-dlp 作为备用方案
                try:
                    return await super().download(resolved_url, output_dir, quality, progress_callback)
                except Exception:
                    raise DownloadFailedError(url, "无法获取视频下载地址")

            # 构建视频信息
            video_info = VideoInfo(
                url=resolved_url,
                platform=Platform.REDNOTE,
                video_id=note_id,
                title=info.get("title", f"小红书笔记_{note_id}"),
                author=info.get("author"),
                thumbnail=info.get("cover"),
            )

            if progress_callback:
                progress_callback.on_start(video_info)

            # 清理文件名
            safe_title = re.sub(r'[\\/:*?"<>|]', '_', video_info.title)[:100]
            output_path = output_dir / f"{safe_title}.mp4"

            # 下载视频
            async with aiohttp.ClientSession() as session:
                headers = self._get_headers()
                headers["Referer"] = resolved_url

                async with session.get(video_url, headers=headers) as response:
                    if response.status != 200:
                        raise DownloadFailedError(url, f"下载失败: HTTP {response.status}")

                    total_size = int(response.headers.get("Content-Length", 0))
                    downloaded = 0

                    with open(output_path, "wb") as f:
                        async for chunk in response.content.iter_chunked(8192):
                            f.write(chunk)
                            downloaded += len(chunk)

                            if progress_callback and total_size > 0:
                                from src.core.models import DownloadProgress
                                progress = DownloadProgress(
                                    status="downloading",
                                    percentage=downloaded / total_size * 100,
                                    downloaded_bytes=downloaded,
                                    total_bytes=total_size,
                                )
                                progress_callback.on_progress(progress)

            elapsed_time = time.time() - start_time
            file_size = output_path.stat().st_size

            result = DownloadResult(
                success=True,
                video_info=video_info,
                file_path=output_path,
                file_size=file_size,
                elapsed_time=elapsed_time,
            )

            if progress_callback:
                progress_callback.on_complete(result)

            return result

        except DownloaderError:
            raise
        except Exception as e:
            # 尝试使用 yt-dlp 作为最后备用方案
            try:
                return await super().download(resolved_url, output_dir, quality, progress_callback)
            except Exception as e2:
                raise DownloadFailedError(
                    url,
                    f"小红书下载失败: {str(e)}。备用方案也失败: {str(e2)}。"
                    "建议设置 REDNOTE_COOKIE 环境变量后重试。"
                )
