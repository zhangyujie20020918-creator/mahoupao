"""
Bilibili 下载器
"""

from pathlib import Path
from typing import Optional

from src.core.models import Platform, VideoInfo
from src.core.interfaces import IProgressCallback
from src.core.exceptions import AuthenticationError
from src.config import get_settings
from .base import BaseDownloader


class BilibiliDownloader(BaseDownloader):
    """Bilibili视频下载器"""

    @property
    def platform(self) -> Platform:
        return Platform.BILIBILI

    @property
    def supported_domains(self) -> list[str]:
        return [
            "bilibili.com",
            "b23.tv",
            "bilibili.tv",
        ]

    def _get_extra_options(self) -> dict:
        """Bilibili特定配置"""
        settings = get_settings()
        options = {
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
            },
        }

        # 添加Cookie支持高清下载
        if settings.platform.bilibili_cookie:
            options["http_headers"]["Cookie"] = settings.platform.bilibili_cookie
        elif settings.platform.bilibili_sessdata:
            options["http_headers"]["Cookie"] = f"SESSDATA={settings.platform.bilibili_sessdata}"

        return options

    def _parse_video_info(self, info: dict, url: str) -> VideoInfo:
        """处理Bilibili特有的字段"""
        video_info = super()._parse_video_info(info, url)

        # Bilibili特有：处理分P信息
        if entries := info.get("entries"):
            # 多P视频
            video_info.description = f"共 {len(entries)} 个分P\n{video_info.description or ''}"

        return video_info

    def check_login_required(self, quality: str = "best") -> bool:
        """检查是否需要登录"""
        settings = get_settings()
        # 1080P及以上需要登录
        high_quality = quality in ["best", "1080p", "4k"]
        has_cookie = bool(
            settings.platform.bilibili_cookie or
            settings.platform.bilibili_sessdata
        )
        return high_quality and not has_cookie

    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ):
        """下载视频，增加登录检查"""
        if self.check_login_required(quality):
            raise AuthenticationError(
                "Bilibili",
                "下载1080P及以上画质需要设置BILIBILI_COOKIE环境变量"
            )

        return await super().download(url, output_dir, quality, progress_callback)
