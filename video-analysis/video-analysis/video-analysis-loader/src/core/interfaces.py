"""
接口定义 - 定义所有抽象接口，实现依赖倒置
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Callable, AsyncGenerator, Protocol, runtime_checkable

from .models import VideoInfo, DownloadResult, DownloadProgress, Platform


class IProgressCallback(ABC):
    """进度回调接口"""

    @abstractmethod
    def on_progress(self, progress: DownloadProgress) -> None:
        """进度更新回调"""
        pass

    @abstractmethod
    def on_start(self, video_info: VideoInfo) -> None:
        """开始下载回调"""
        pass

    @abstractmethod
    def on_complete(self, result: DownloadResult) -> None:
        """下载完成回调"""
        pass

    @abstractmethod
    def on_error(self, error: Exception) -> None:
        """错误回调"""
        pass


class IDownloader(ABC):
    """下载器接口 - 所有平台下载器必须实现此接口"""

    @property
    @abstractmethod
    def platform(self) -> Platform:
        """返回此下载器支持的平台"""
        pass

    @property
    @abstractmethod
    def supported_domains(self) -> list[str]:
        """返回支持的域名列表"""
        pass

    @abstractmethod
    def supports_url(self, url: str) -> bool:
        """检查是否支持该URL"""
        pass

    @abstractmethod
    async def get_video_info(self, url: str) -> VideoInfo:
        """获取视频信息（不下载）"""
        pass

    @abstractmethod
    async def download(
        self,
        url: str,
        output_dir: Path,
        quality: str = "best",
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """下载视频"""
        pass

    @abstractmethod
    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """仅下载音频"""
        pass


class IUrlParser(ABC):
    """URL解析器接口"""

    @abstractmethod
    def parse(self, url: str) -> tuple[Platform, str]:
        """
        解析URL，返回平台和视频ID
        Returns:
            tuple: (Platform, video_id)
        """
        pass

    @abstractmethod
    def normalize(self, url: str) -> str:
        """标准化URL"""
        pass

    @abstractmethod
    def is_valid(self, url: str) -> bool:
        """检查URL是否有效"""
        pass


class IDownloadService(ABC):
    """下载服务接口 - 高层业务逻辑"""

    @abstractmethod
    def register_downloader(self, downloader: IDownloader) -> None:
        """注册下载器"""
        pass

    @abstractmethod
    async def download(
        self,
        url: str,
        output_dir: Optional[Path] = None,
        quality: str = "best",
        audio_only: bool = False,
        progress_callback: Optional[IProgressCallback] = None,
    ) -> DownloadResult:
        """统一下载入口"""
        pass

    @abstractmethod
    async def get_info(self, url: str) -> VideoInfo:
        """获取视频信息"""
        pass

    @abstractmethod
    async def batch_download(
        self,
        urls: list[str],
        output_dir: Optional[Path] = None,
        quality: str = "best",
    ) -> list[DownloadResult]:
        """批量下载"""
        pass


@runtime_checkable
class IUserProfileDownloader(Protocol):
    """可选协议：支持用户主页批量下载的下载器实现此接口

    下载器只需实现这两个方法即可自动被 DownloadService 识别和调用，
    无需修改 IDownloader 或任何上层代码。
    """

    def is_user_profile_url(self, url: str) -> bool:
        """判断 URL 是否为用户主页"""
        ...

    async def download_user_videos_stream(
        self,
        user_url: str,
        output_dir: Path,
        quality: str = "best",
        max_retries: int = 3,
    ) -> AsyncGenerator[dict, None]:
        """流式下载用户主页视频，yield 标准 SSE 事件 dict

        事件格式参见 src.core.events 中的工厂函数。
        """
        ...
