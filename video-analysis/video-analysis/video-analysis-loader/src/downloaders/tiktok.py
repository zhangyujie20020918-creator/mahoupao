"""
TikTok 国际版下载器
"""

from pathlib import Path
from typing import Optional

from src.core.models import Platform, VideoInfo, DownloadResult
from src.core.interfaces import IProgressCallback
from src.core.exceptions import DownloaderError
from .base import BaseDownloader


class TikTokDownloader(BaseDownloader):
    """TikTok 国际版视频下载器"""

    @property
    def platform(self) -> Platform:
        return Platform.TIKTOK

    @property
    def supported_domains(self) -> list[str]:
        return [
            "tiktok.com",
            "vm.tiktok.com",
            "vt.tiktok.com",
        ]

    def _check_url_type(self, url: str) -> None:
        """检查URL类型，图片帖子不支持下载"""
        if "/photo/" in url:
            raise DownloaderError(
                url=url,
                message="此链接为图片帖子，暂不支持下载。请使用视频链接。"
            )

    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息"""
        self._check_url_type(url)
        return await super().get_video_info(url)

    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载视频"""
        self._check_url_type(url)
        return await super().download(url, output_dir, quality, progress_callback)

    def _get_extra_options(self) -> dict:
        """TikTok特定配置"""
        options = {
            # 添加必要的请求头
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.tiktok.com/",
            },
            # 使用最佳可用格式，带回退选项
            "format": "best[ext=mp4]/best",
        }

        return options
