"""
下载器工厂 - 负责创建和管理下载器实例
实现策略模式，根据URL自动选择合适的下载器
"""

from typing import Dict, Type, Optional

from src.core.interfaces import IDownloader
from src.core.models import Platform
from src.core.exceptions import UnsupportedPlatformError
from src.downloaders import (
    YouTubeDownloader,
    TikTokDownloader,
    DouyinDownloader,
    BilibiliDownloader,
    RedNoteDownloader,
)


class DownloaderFactory:
    """
    下载器工厂

    使用方式:
        factory = DownloaderFactory()
        downloader = factory.get_downloader_for_url(url)
        result = await downloader.download(url, output_dir)

    扩展新平台:
        factory.register(Platform.NEW_PLATFORM, NewDownloader)
    """

    def __init__(self, auto_register: bool = True):
        """
        初始化工厂

        Args:
            auto_register: 是否自动注册内置下载器
        """
        self._downloaders: Dict[Platform, IDownloader] = {}
        self._downloader_classes: Dict[Platform, Type[IDownloader]] = {}

        if auto_register:
            self._register_builtin_downloaders()

    def _register_builtin_downloaders(self) -> None:
        """注册内置下载器"""
        self.register(Platform.YOUTUBE, YouTubeDownloader)
        self.register(Platform.TIKTOK, TikTokDownloader)
        self.register(Platform.DOUYIN, DouyinDownloader)
        self.register(Platform.BILIBILI, BilibiliDownloader)
        self.register(Platform.REDNOTE, RedNoteDownloader)

    def register(
        self,
        platform: Platform,
        downloader_class: Type[IDownloader]
    ) -> None:
        """
        注册下载器类

        Args:
            platform: 平台类型
            downloader_class: 下载器类（不是实例）
        """
        self._downloader_classes[platform] = downloader_class
        # 清除已缓存的实例，下次使用时重新创建
        if platform in self._downloaders:
            del self._downloaders[platform]

    def get_downloader(self, platform: Platform) -> IDownloader:
        """
        获取指定平台的下载器实例（懒加载单例）

        Args:
            platform: 平台类型

        Returns:
            下载器实例

        Raises:
            UnsupportedPlatformError: 不支持的平台
        """
        if platform not in self._downloader_classes:
            raise UnsupportedPlatformError(f"平台 {platform.name}")

        # 懒加载：首次使用时创建实例
        if platform not in self._downloaders:
            self._downloaders[platform] = self._downloader_classes[platform]()

        return self._downloaders[platform]

    def get_downloader_for_url(self, url: str) -> IDownloader:
        """
        根据URL自动选择合适的下载器

        Args:
            url: 视频URL

        Returns:
            下载器实例

        Raises:
            UnsupportedPlatformError: 无法识别URL对应的平台
        """
        platform = Platform.from_url(url)

        if platform == Platform.UNKNOWN:
            # 尝试遍历所有下载器检查是否支持
            for p, downloader_class in self._downloader_classes.items():
                downloader = self.get_downloader(p)
                if downloader.supports_url(url):
                    return downloader
            raise UnsupportedPlatformError(url)

        return self.get_downloader(platform)

    def get_supported_platforms(self) -> list[Platform]:
        """获取所有支持的平台列表"""
        return list(self._downloader_classes.keys())

    def get_supported_domains(self) -> list[str]:
        """获取所有支持的域名列表"""
        domains = []
        for platform in self._downloader_classes:
            downloader = self.get_downloader(platform)
            domains.extend(downloader.supported_domains)
        return domains


# 全局工厂实例（可选使用）
_default_factory: Optional[DownloaderFactory] = None


def get_factory() -> DownloaderFactory:
    """获取全局工厂实例"""
    global _default_factory
    if _default_factory is None:
        _default_factory = DownloaderFactory()
    return _default_factory
