"""
数据模型定义
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Optional, List


class Platform(Enum):
    """支持的平台枚举"""
    YOUTUBE = auto()
    TIKTOK = auto()  # TikTok 国际版
    DOUYIN = auto()  # 抖音（中国版）
    BILIBILI = auto()
    REDNOTE = auto()  # 小红书
    UNKNOWN = auto()

    @classmethod
    def from_url(cls, url: str) -> "Platform":
        """根据URL识别平台"""
        url_lower = url.lower()

        if any(domain in url_lower for domain in ["youtube.com", "youtu.be"]):
            return cls.YOUTUBE
        elif any(domain in url_lower for domain in ["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"]):
            return cls.TIKTOK
        elif any(domain in url_lower for domain in ["douyin.com", "iesdouyin.com"]):
            return cls.DOUYIN
        elif "bilibili.com" in url_lower or "b23.tv" in url_lower:
            return cls.BILIBILI
        elif any(domain in url_lower for domain in ["xiaohongshu.com", "xhslink.com"]):
            return cls.REDNOTE
        else:
            return cls.UNKNOWN


@dataclass
class VideoInfo:
    """视频信息"""
    url: str
    platform: Platform
    video_id: str
    title: str
    author: Optional[str] = None
    duration: Optional[int] = None  # 秒
    thumbnail: Optional[str] = None
    description: Optional[str] = None
    upload_date: Optional[datetime] = None
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    available_qualities: List[str] = field(default_factory=list)

    # 原始数据（用于调试或扩展）
    raw_data: Optional[dict] = field(default=None, repr=False)


@dataclass
class DownloadProgress:
    """下载进度"""
    downloaded_bytes: int = 0
    total_bytes: Optional[int] = None
    speed: float = 0.0  # bytes/s
    eta: Optional[int] = None  # 预计剩余秒数
    percentage: float = 0.0
    status: str = "downloading"  # downloading, merging, finished, error

    @property
    def speed_human(self) -> str:
        """人类可读的速度"""
        if self.speed < 1024:
            return f"{self.speed:.1f} B/s"
        elif self.speed < 1024 * 1024:
            return f"{self.speed / 1024:.1f} KB/s"
        else:
            return f"{self.speed / (1024 * 1024):.1f} MB/s"


@dataclass
class DownloadResult:
    """下载结果"""
    success: bool
    video_info: VideoInfo
    file_path: Optional[Path] = None
    file_size: Optional[int] = None
    error_message: Optional[str] = None
    elapsed_time: float = 0.0  # 秒
    subtitle_path: Optional[Path] = None  # 字幕文件路径

    @property
    def file_size_human(self) -> str:
        """人类可读的文件大小"""
        if not self.file_size:
            return "未知"
        if self.file_size < 1024:
            return f"{self.file_size} B"
        elif self.file_size < 1024 * 1024:
            return f"{self.file_size / 1024:.1f} KB"
        elif self.file_size < 1024 * 1024 * 1024:
            return f"{self.file_size / (1024 * 1024):.1f} MB"
        else:
            return f"{self.file_size / (1024 * 1024 * 1024):.2f} GB"
