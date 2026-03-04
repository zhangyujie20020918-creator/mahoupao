"""
进度处理器实现
"""

from rich.console import Console
from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
)

from src.core.interfaces import IProgressCallback
from src.core.models import VideoInfo, DownloadResult, DownloadProgress


class ConsoleProgressHandler(IProgressCallback):
    """控制台进度显示器"""

    def __init__(self):
        self.console = Console()
        self._progress: Progress | None = None
        self._task_id = None
        self._started = False

    def _create_progress(self) -> Progress:
        """创建Rich进度条"""
        return Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=40),
            "[progress.percentage]{task.percentage:>3.0f}%",
            "•",
            DownloadColumn(),
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=self.console,
        )

    def on_start(self, video_info: VideoInfo) -> None:
        """开始下载"""
        self.console.print()
        self.console.print(f"[bold green]📹 开始下载[/]")
        self.console.print(f"   标题: [cyan]{video_info.title}[/]")
        if video_info.author:
            self.console.print(f"   作者: {video_info.author}")
        if video_info.duration:
            minutes, seconds = divmod(video_info.duration, 60)
            self.console.print(f"   时长: {minutes}:{seconds:02d}")
        self.console.print()

        self._progress = self._create_progress()
        self._progress.start()
        self._task_id = self._progress.add_task(
            "下载中...",
            total=100,
        )
        self._started = True

    def on_progress(self, progress: DownloadProgress) -> None:
        """更新进度"""
        if not self._started or self._progress is None:
            return

        description = {
            "downloading": "下载中...",
            "merging": "合并中...",
            "finished": "完成!",
            "error": "出错",
        }.get(progress.status, progress.status)

        self._progress.update(
            self._task_id,
            completed=progress.percentage,
            description=description,
        )

    def on_complete(self, result: DownloadResult) -> None:
        """下载完成"""
        if self._progress:
            self._progress.update(
                self._task_id,
                completed=100,
                description="完成!",
            )
            self._progress.stop()

        self.console.print()
        if result.success:
            self.console.print("[bold green]✓ 下载完成![/]")
            if result.file_path:
                self.console.print(f"   文件: [cyan]{result.file_path}[/]")
            self.console.print(f"   大小: {result.file_size_human}")
            self.console.print(f"   耗时: {result.elapsed_time:.1f}秒")
        else:
            self.console.print(f"[bold red]✗ 下载失败: {result.error_message}[/]")

    def on_error(self, error: Exception) -> None:
        """发生错误"""
        if self._progress:
            self._progress.stop()

        self.console.print()
        self.console.print(f"[bold red]✗ 错误: {str(error)}[/]")


class SilentProgressHandler(IProgressCallback):
    """静默进度处理器（用于批量下载或API调用）"""

    def on_start(self, video_info: VideoInfo) -> None:
        pass

    def on_progress(self, progress: DownloadProgress) -> None:
        pass

    def on_complete(self, result: DownloadResult) -> None:
        pass

    def on_error(self, error: Exception) -> None:
        pass
