"""
CLI 入口 - 命令行界面
"""

import asyncio
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from src import __version__
from src.services import DownloadService, ConsoleProgressHandler
from src.downloaders.douyin import DouyinDownloader
from src.core.models import Platform
from src.core.exceptions import DownloaderError


console = Console()


def print_banner():
    """打印横幅"""
    console.print()
    console.print("[bold cyan]╔════════════════════════════════════════╗[/]")
    console.print("[bold cyan]║[/]    [bold white]Video Downloader[/] [dim]v{}[/]         [bold cyan]║[/]".format(__version__))
    console.print("[bold cyan]║[/]    [dim]YouTube | TikTok | Bilibili | 小红书[/]  [bold cyan]║[/]")
    console.print("[bold cyan]╚════════════════════════════════════════╝[/]")
    console.print()


@click.group()
@click.version_option(version=__version__)
def cli():
    """多平台视频下载工具"""
    pass


@cli.command()
@click.argument("url")
@click.option(
    "-o", "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="输出目录",
)
@click.option(
    "-q", "--quality",
    type=click.Choice(["best", "1080p", "720p", "480p"]),
    default="best",
    help="视频画质",
)
@click.option(
    "--audio-only",
    is_flag=True,
    help="仅下载音频",
)
@click.option(
    "--quiet",
    is_flag=True,
    help="安静模式，不显示进度",
)
def download(
    url: str,
    output: Optional[Path],
    quality: str,
    audio_only: bool,
    quiet: bool,
):
    """下载视频

    URL: 视频链接
    """
    if not quiet:
        print_banner()

    service = DownloadService()
    progress = None if quiet else ConsoleProgressHandler()

    try:
        result = asyncio.run(
            service.download(
                url=url,
                output_dir=output,
                quality=quality,
                audio_only=audio_only,
                progress_callback=progress,
            )
        )

        if not result.success:
            console.print(f"[red]下载失败: {result.error_message}[/]")
            sys.exit(1)

    except DownloaderError as e:
        console.print(f"[red]错误: {e.message}[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]未知错误: {str(e)}[/]")
        sys.exit(1)


@cli.command()
@click.argument("url")
def info(url: str):
    """获取视频信息（不下载）"""
    print_banner()

    service = DownloadService()

    try:
        video_info = asyncio.run(service.get_info(url))

        table = Table(title="视频信息", show_header=False)
        table.add_column("字段", style="cyan")
        table.add_column("值")

        table.add_row("平台", video_info.platform.name)
        table.add_row("视频ID", video_info.video_id)
        table.add_row("标题", video_info.title)

        if video_info.author:
            table.add_row("作者", video_info.author)

        if video_info.duration:
            minutes, seconds = divmod(video_info.duration, 60)
            hours, minutes = divmod(minutes, 60)
            if hours:
                table.add_row("时长", f"{hours}:{minutes:02d}:{seconds:02d}")
            else:
                table.add_row("时长", f"{minutes}:{seconds:02d}")

        if video_info.view_count:
            table.add_row("播放量", f"{video_info.view_count:,}")

        if video_info.like_count:
            table.add_row("点赞数", f"{video_info.like_count:,}")

        if video_info.available_qualities:
            table.add_row("可用画质", ", ".join(video_info.available_qualities))

        console.print(table)

    except DownloaderError as e:
        console.print(f"[red]错误: {e.message}[/]")
        sys.exit(1)


@cli.command()
@click.argument("urls", nargs=-1, required=True)
@click.option(
    "-o", "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="输出目录",
)
@click.option(
    "-q", "--quality",
    type=click.Choice(["best", "1080p", "720p", "480p"]),
    default="best",
    help="视频画质",
)
@click.option(
    "-c", "--concurrent",
    type=int,
    default=3,
    help="最大并发下载数",
)
def batch(
    urls: tuple,
    output: Optional[Path],
    quality: str,
    concurrent: int,
):
    """批量下载视频

    URLS: 多个视频链接
    """
    print_banner()
    console.print(f"[cyan]准备下载 {len(urls)} 个视频...[/]")
    console.print()

    service = DownloadService()

    results = asyncio.run(
        service.batch_download(
            urls=list(urls),
            output_dir=output,
            quality=quality,
            max_concurrent=concurrent,
        )
    )

    # 显示结果摘要
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count

    console.print()
    console.print(f"[bold]下载完成:[/] [green]{success_count} 成功[/], [red]{fail_count} 失败[/]")

    if fail_count > 0:
        console.print()
        console.print("[bold red]失败的下载:[/]")
        for result in results:
            if not result.success:
                console.print(f"  - {result.video_info.url}")
                console.print(f"    [dim]{result.error_message}[/]")


@cli.command(name="user-download")
@click.argument("url")
@click.option(
    "-o", "--output",
    type=click.Path(path_type=Path),
    default=None,
    help="输出目录",
)
@click.option(
    "-q", "--quality",
    type=click.Choice(["best", "1080p", "720p", "480p"]),
    default="best",
    help="视频画质",
)
@click.option(
    "-c", "--concurrent",
    type=int,
    default=1,
    help="最大并发下载数（抖音建议设为1，避免被限流）",
)
@click.option(
    "--max-scroll",
    type=int,
    default=50,
    help="最大滚动次数，用于加载更多视频",
)
def user_download(
    url: str,
    output: Optional[Path],
    quality: str,
    concurrent: int,
    max_scroll: int,
):
    """从抖音用户主页批量下载所有视频

    URL: 抖音用户主页链接
    """
    print_banner()

    console.print("[cyan]正在解析用户主页，提取视频链接...[/]")
    console.print("[dim]（浏览器将自动打开并滚动页面加载视频列表）[/]")
    console.print()

    downloader = DouyinDownloader()

    try:
        video_urls = asyncio.run(downloader.extract_user_video_urls(url, max_scroll))
    except DownloaderError as e:
        console.print(f"[red]提取视频链接失败: {e.message}[/]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]提取视频链接失败: {str(e)}[/]")
        sys.exit(1)

    if not video_urls:
        console.print("[yellow]未找到任何视频链接。可能原因：[/]")
        console.print("  1. 用户主页无视频内容")
        console.print("  2. 页面结构中不存在 userNewUi 容器")
        console.print("  3. 需要先在浏览器中完成登录/验证")
        sys.exit(1)

    console.print(f"[bold green]共找到 {len(video_urls)} 个视频链接[/]")
    console.print()

    # 显示前10个链接预览
    preview_count = min(10, len(video_urls))
    for i, vurl in enumerate(video_urls[:preview_count], 1):
        console.print(f"  {i}. [dim]{vurl}[/]")
    if len(video_urls) > preview_count:
        console.print(f"  ... 还有 {len(video_urls) - preview_count} 个视频")
    console.print()

    console.print(f"[cyan]开始批量下载，并发数: {concurrent}[/]")
    console.print()

    service = DownloadService()

    results = asyncio.run(
        service.batch_download(
            urls=video_urls,
            output_dir=output,
            quality=quality,
            max_concurrent=concurrent,
        )
    )

    # 显示结果摘要
    success_count = sum(1 for r in results if r.success)
    fail_count = len(results) - success_count

    console.print()
    console.print(f"[bold]下载完成:[/] [green]{success_count} 成功[/], [red]{fail_count} 失败[/]")

    if fail_count > 0:
        console.print()
        console.print("[bold red]失败的下载:[/]")
        for result in results:
            if not result.success:
                console.print(f"  - {result.video_info.url}")
                console.print(f"    [dim]{result.error_message}[/]")


@cli.command()
def platforms():
    """显示支持的平台"""
    print_banner()

    table = Table(title="支持的平台")
    table.add_column("平台", style="cyan")
    table.add_column("支持的域名")

    platforms_data = [
        ("YouTube", "youtube.com, youtu.be"),
        ("TikTok / 抖音", "tiktok.com, douyin.com"),
        ("Bilibili", "bilibili.com, b23.tv"),
        ("小红书", "xiaohongshu.com, xhslink.com"),
    ]

    for name, domains in platforms_data:
        table.add_row(name, domains)

    console.print(table)


def main():
    """程序入口"""
    cli()


if __name__ == "__main__":
    main()
