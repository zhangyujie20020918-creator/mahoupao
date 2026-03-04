"""
下载服务 - 高层业务逻辑封装
提供统一的下载接口，隐藏底层复杂性
"""

import asyncio
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Any

from src.core.interfaces import IDownloader, IDownloadService, IProgressCallback, IUserProfileDownloader
from src.core.models import VideoInfo, DownloadResult, Platform
from src.core.exceptions import UnsupportedPlatformError, DownloaderError
from src.config import get_settings
from .factory import DownloaderFactory
from .progress_handler import SilentProgressHandler


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

    def is_user_profile_url(self, url: str) -> bool:
        """通用检测：是否有下载器支持此 URL 的用户主页下载"""
        try:
            downloader = self._factory.get_downloader_for_url(url)
        except UnsupportedPlatformError:
            return False
        return isinstance(downloader, IUserProfileDownloader) and downloader.is_user_profile_url(url)

    async def download_user_videos(
        self,
        user_url: str,
        output_dir: Optional[Path] = None,
        quality: str = "best",
    ) -> list[DownloadResult]:
        """下载用户主页所有视频（通用接口，自动选择平台下载器）"""
        output_dir = output_dir or self._settings.download.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, IUserProfileDownloader):
            raise DownloaderError(url=user_url, message="该平台不支持用户主页下载")

        platform = Platform.from_url(user_url)
        results: list[DownloadResult] = []
        async for event in downloader.download_user_videos_stream(user_url, output_dir, quality):
            if event.get("type") == "downloaded":
                success = event.get("success", False)
                file_path = Path(event["file_path"]) if event.get("file_path") else None
                file_size = file_path.stat().st_size if file_path and file_path.exists() else None

                results.append(DownloadResult(
                    success=success,
                    video_info=VideoInfo(
                        url=event.get("url", user_url),
                        platform=platform,
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
        流式下载用户主页视频（通用接口）。
        委托给实现了 IUserProfileDownloader 协议的平台下载器。
        """
        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, IUserProfileDownloader):
            yield {"type": "error", "message": "该平台不支持用户主页下载"}
            return

        async for event in downloader.download_user_videos_stream(
            user_url, output_dir, quality, max_retries
        ):
            yield event

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
