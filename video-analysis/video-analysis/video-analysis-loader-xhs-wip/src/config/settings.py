"""
配置管理模块 - 集中管理所有配置项
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import os


def _get_default_output_dir() -> Path:
    """获取默认下载目录（video-analysis根目录下的downloads）"""
    # 获取 video-analysis 根目录
    current_file = Path(__file__).resolve()
    # src/config/settings.py -> video-analysis-python -> video-analysis -> downloads
    video_analysis_root = current_file.parent.parent.parent.parent
    return video_analysis_root / "downloads"


@dataclass
class DownloadSettings:
    """下载相关配置"""
    output_dir: Path = field(default_factory=_get_default_output_dir)
    max_retries: int = 3
    timeout: int = 30
    chunk_size: int = 8192
    prefer_quality: str = "best"  # best, 1080p, 720p, 480p
    with_audio: bool = True


@dataclass
class ProxySettings:
    """代理配置"""
    enabled: bool = False
    http: Optional[str] = None
    https: Optional[str] = None


@dataclass
class PlatformSettings:
    """平台特定配置"""
    # Bilibili
    bilibili_cookie: Optional[str] = None
    bilibili_sessdata: Optional[str] = None

    # 小红书
    rednote_cookie: Optional[str] = None

    # TikTok
    tiktok_no_watermark: bool = True


@dataclass
class Settings:
    """全局配置"""
    download: DownloadSettings = field(default_factory=DownloadSettings)
    proxy: ProxySettings = field(default_factory=ProxySettings)
    platform: PlatformSettings = field(default_factory=PlatformSettings)

    def __post_init__(self):
        # 确保下载目录存在
        self.download.output_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "Settings":
        """从环境变量加载配置"""
        settings = cls()

        # 下载目录
        if output_dir := os.getenv("VIDEO_DL_OUTPUT_DIR"):
            settings.download.output_dir = Path(output_dir)

        # 代理
        if http_proxy := os.getenv("HTTP_PROXY"):
            settings.proxy.enabled = True
            settings.proxy.http = http_proxy
        if https_proxy := os.getenv("HTTPS_PROXY"):
            settings.proxy.enabled = True
            settings.proxy.https = https_proxy

        # Bilibili Cookie
        if bili_cookie := os.getenv("BILIBILI_COOKIE"):
            settings.platform.bilibili_cookie = bili_cookie

        return settings


# 单例模式
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """获取全局配置单例"""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings
