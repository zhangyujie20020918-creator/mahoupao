"""
YouTube 下载器
"""

from src.core.models import Platform
from .base import BaseDownloader


class YouTubeDownloader(BaseDownloader):
    """YouTube视频下载器"""

    @property
    def platform(self) -> Platform:
        return Platform.YOUTUBE

    @property
    def supported_domains(self) -> list[str]:
        return [
            "youtube.com",
            "youtu.be",
            "youtube-nocookie.com",
            "music.youtube.com",
        ]

    def _get_extra_options(self) -> dict:
        """YouTube特定配置"""
        return {
            # 使用更稳定的格式选择
            "format_sort": ["res:1080", "ext:mp4:m4a"],
            # 跳过年龄限制检查
            "age_limit": None,
            # 处理直播回放
            "live_from_start": True,
        }
