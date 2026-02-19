"""
下载服务 - 高层业务逻辑封装
提供统一的下载接口，隐藏底层复杂性
"""

import asyncio
import time
from pathlib import Path
from typing import Optional, List, AsyncGenerator, Any

from src.core.interfaces import IDownloader, IDownloadService, IProgressCallback
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
        """
        初始化服务

        Args:
            factory: 下载器工厂，为None时使用默认工厂
        """
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
        """
        下载视频

        Args:
            url: 视频URL
            output_dir: 输出目录，为None时使用默认目录
            quality: 画质选择 (best, 1080p, 720p, 480p)
            audio_only: 是否仅下载音频
            progress_callback: 进度回调

        Returns:
            DownloadResult: 下载结果
        """
        output_dir = output_dir or self._settings.download.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        downloader = self._factory.get_downloader_for_url(url)

        if audio_only:
            return await downloader.download_audio_only(
                url, output_dir, progress_callback
            )
        else:
            return await downloader.download(
                url, output_dir, quality, progress_callback
            )

    async def get_info(self, url: str) -> VideoInfo:
        """
        获取视频信息（不下载）

        Args:
            url: 视频URL

        Returns:
            VideoInfo: 视频信息
        """
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
        """
        批量下载视频

        Args:
            urls: 视频URL列表
            output_dir: 输出目录
            quality: 画质
            max_concurrent: 最大并发数
            progress_callback: 进度回调（批量下载时建议使用静默处理器）

        Returns:
            下载结果列表
        """
        output_dir = output_dir or self._settings.download.output_dir
        callback = progress_callback or SilentProgressHandler()

        semaphore = asyncio.Semaphore(max_concurrent)

        async def download_with_limit(url: str) -> DownloadResult:
            async with semaphore:
                try:
                    return await self.download(
                        url, output_dir, quality, False, callback
                    )
                except Exception as e:
                    # 返回失败结果而不是抛出异常
                    platform = Platform.from_url(url)
                    return DownloadResult(
                        success=False,
                        video_info=VideoInfo(
                            url=url,
                            platform=platform,
                            video_id="",
                            title="下载失败",
                        ),
                        error_message=str(e),
                    )

        tasks = [download_with_limit(url) for url in urls]
        return await asyncio.gather(*tasks)

    async def download_user_videos(
        self,
        user_url: str,
        output_dir: Optional[Path] = None,
        quality: str = "best",
    ) -> list[DownloadResult]:
        """
        下载抖音用户主页所有视频

        Args:
            user_url: 用户主页URL
            output_dir: 输出目录
            quality: 画质

        Returns:
            下载结果列表
        """
        from src.downloaders.douyin import DouyinDownloader

        output_dir = output_dir or self._settings.download.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, DouyinDownloader):
            raise DownloaderError(url=user_url, message="用户主页下载仅支持抖音平台")

        video_urls = await downloader.extract_user_video_urls(user_url, interactive=False)
        if not video_urls:
            raise DownloaderError(url=user_url, message="未从用户主页提取到任何视频链接")

        return await self.batch_download(video_urls, output_dir, quality)

    async def download_user_videos_stream(
        self,
        user_url: str,
        output_dir: Path,
        quality: str = "best",
        max_retries: int = 3,
    ) -> AsyncGenerator[dict, None]:
        """
        流式下载抖音用户主页视频，逐个 yield 事件。

        下载策略：
        - 逐个下载，每完成一个对比已下载数 vs 总数
        - 已成功的视频不会重复下载
        - 单个视频失败后会重试，最多 max_retries 次
        - 连续失败 max_retries 次的视频移出下载列表
        - 全部完成后汇报被移除的失败视频，由用户手动确认
        """
        from src.downloaders.douyin import DouyinDownloader

        output_dir.mkdir(parents=True, exist_ok=True)
        start_time = time.time()

        yield {"type": "extracting", "message": "正在提取视频链接..."}

        downloader = self._factory.get_downloader_for_url(user_url)
        if not isinstance(downloader, DouyinDownloader):
            yield {"type": "error", "message": "用户主页下载仅支持抖音平台"}
            return

        video_urls = await downloader.extract_user_video_urls(user_url, interactive=False)
        if not video_urls:
            yield {"type": "error", "message": "未从用户主页提取到任何视频链接"}
            return

        total = len(video_urls)
        yield {"type": "extracted", "total": total, "message": f"提取到 {total} 个视频链接"}

        # 状态跟踪
        succeeded_urls: set[str] = set()   # 已成功下载的 URL
        fail_count: dict[str, int] = {}    # URL → 连续失败次数
        skipped: list[dict] = []           # 失败 3 次被移除的视频信息
        callback = SilentProgressHandler()
        download_index = 0                 # 全局下载序号（含重试）

        # 构建待下载队列（排除已成功的）
        pending = list(video_urls)

        while pending:
            url = pending.pop(0)

            # 跳过已成功的
            if url in succeeded_urls:
                continue

            download_index += 1
            attempt = fail_count.get(url, 0) + 1
            remaining = total - len(succeeded_urls) - len(skipped)

            yield {
                "type": "downloading",
                "index": download_index,
                "total": total,
                "url": url,
                "succeeded_so_far": len(succeeded_urls),
                "remaining": remaining,
                "attempt": attempt,
            }

            try:
                result = await self.download(url, output_dir, quality, False, callback)
                if result.success:
                    succeeded_urls.add(url)
                    fail_count.pop(url, None)
                    yield {
                        "type": "downloaded",
                        "index": download_index,
                        "total": total,
                        "title": result.video_info.title if result.video_info else "未知",
                        "success": True,
                        "file_path": str(result.file_path) if result.file_path else None,
                        "file_size_human": result.file_size_human,
                        "succeeded_so_far": len(succeeded_urls),
                        "remaining": total - len(succeeded_urls) - len(skipped),
                    }
                else:
                    # 下载失败，记录重试
                    fail_count[url] = attempt
                    title = result.video_info.title if result.video_info else "未知"
                    error_msg = result.error_message or "下载失败"

                    if attempt >= max_retries:
                        # 达到最大重试次数，移出列表
                        skipped.append({"url": url, "title": title, "error": error_msg})
                        yield {
                            "type": "downloaded",
                            "index": download_index,
                            "total": total,
                            "title": title,
                            "success": False,
                            "error": f"[已跳过] 连续失败{max_retries}次: {error_msg}",
                            "attempt": attempt,
                            "permanently_failed": True,
                        }
                    else:
                        # 还有重试机会，放回队列末尾
                        pending.append(url)
                        yield {
                            "type": "downloaded",
                            "index": download_index,
                            "total": total,
                            "title": title,
                            "success": False,
                            "error": f"[第{attempt}次失败，稍后重试] {error_msg}",
                            "attempt": attempt,
                            "permanently_failed": False,
                        }

            except Exception as e:
                fail_count[url] = attempt
                error_msg = str(e)

                if attempt >= max_retries:
                    skipped.append({"url": url, "title": "未知", "error": error_msg})
                    yield {
                        "type": "downloaded",
                        "index": download_index,
                        "total": total,
                        "title": "未知",
                        "success": False,
                        "error": f"[已跳过] 连续失败{max_retries}次: {error_msg}",
                        "attempt": attempt,
                        "permanently_failed": True,
                    }
                else:
                    pending.append(url)
                    yield {
                        "type": "downloaded",
                        "index": download_index,
                        "total": total,
                        "title": "未知",
                        "success": False,
                        "error": f"[第{attempt}次失败，稍后重试] {error_msg}",
                        "attempt": attempt,
                        "permanently_failed": False,
                    }

        yield {
            "type": "done",
            "total": total,
            "succeeded": len(succeeded_urls),
            "failed": len(skipped),
            "skipped_videos": skipped,
            "elapsed_time": round(time.time() - start_time, 1),
            "folder_path": str(output_dir),
        }

    def get_supported_platforms(self) -> list[str]:
        """获取支持的平台名称列表"""
        return [p.name for p in self._factory.get_supported_platforms()]

    def get_supported_domains(self) -> list[str]:
        """获取支持的域名列表"""
        return self._factory.get_supported_domains()

    def is_url_supported(self, url: str) -> bool:
        """检查URL是否支持"""
        try:
            self._factory.get_downloader_for_url(url)
            return True
        except UnsupportedPlatformError:
            return False
