"""
API 路由
"""

import asyncio
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse, StreamingResponse

from src.services import DownloadService
from src.core.exceptions import DownloaderError, UnsupportedPlatformError
from src.config import get_settings
from .schemas import (
    DownloadRequest,
    DownloadResponse,
    VideoInfoRequest,
    VideoInfoResponse,
    PlatformsResponse,
    PlatformInfo,
    DownloadProgressResponse,
    ErrorResponse,
    BatchDownloadResponse,
    BatchDownloadItemResponse,
)

router = APIRouter(tags=["Video Download"])

# 下载任务状态存储（生产环境应使用Redis）
download_tasks: dict = {}


def get_service() -> DownloadService:
    """获取下载服务实例"""
    return DownloadService()


def _resolve_output_dir(request: "DownloadRequest") -> Path:
    """根据请求参数解析最终输出目录"""
    import re
    settings = get_settings()

    base_dir = Path(request.output_dir) if request.output_dir else settings.download.output_dir

    if request.folder_name:
        safe_name = re.sub(r'[\\/*?:"<>|]', "_", request.folder_name).strip("_")[:100]
        if safe_name:
            base_dir = base_dir / safe_name

    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


@router.get(
    "/platforms",
    response_model=PlatformsResponse,
    summary="获取支持的平台列表",
)
async def get_platforms():
    """返回所有支持的视频平台"""
    platforms = [
        PlatformInfo(
            name="YouTube",
            value="youtube",
            domains=["youtube.com", "youtu.be"],
        ),
        PlatformInfo(
            name="TikTok",
            value="tiktok",
            domains=["tiktok.com", "vm.tiktok.com", "vt.tiktok.com"],
        ),
        PlatformInfo(
            name="抖音",
            value="douyin",
            domains=["douyin.com", "v.douyin.com", "iesdouyin.com"],
        ),
        PlatformInfo(
            name="Bilibili",
            value="bilibili",
            domains=["bilibili.com", "b23.tv"],
        ),
        PlatformInfo(
            name="小红书",
            value="rednote",
            domains=["xiaohongshu.com", "xhslink.com"],
        ),
    ]
    return PlatformsResponse(platforms=platforms)


@router.get(
    "/download/default-dir",
    summary="获取默认下载目录",
)
async def get_default_dir():
    """返回当前配置的默认下载目录路径"""
    settings = get_settings()
    return {"path": str(settings.download.output_dir)}


@router.post(
    "/info",
    response_model=VideoInfoResponse,
    responses={400: {"model": ErrorResponse}},
    summary="获取视频信息",
)
async def get_video_info(request: VideoInfoRequest):
    """获取视频详细信息（不下载）"""
    service = get_service()

    try:
        info = await service.get_info(request.url)
        return VideoInfoResponse(
            url=info.url,
            platform=info.platform.name,
            video_id=info.video_id,
            title=info.title,
            author=info.author,
            duration=info.duration,
            thumbnail=info.thumbnail,
            description=info.description,
            view_count=info.view_count,
            like_count=info.like_count,
            available_qualities=info.available_qualities,
        )
    except UnsupportedPlatformError as e:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {e.url}")
    except DownloaderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/download",
    responses={400: {"model": ErrorResponse}},
    summary="下载视频",
)
async def download_video(request: DownloadRequest):
    """
    同步下载视频

    支持单个视频URL和用户主页URL（抖音）。
    用户主页URL会自动提取所有视频并批量下载，返回 BatchDownloadResponse。
    """
    from src.downloaders.douyin import DouyinDownloader

    service = get_service()

    try:
        output_dir = _resolve_output_dir(request)

        # 检测是否为抖音用户主页URL
        if DouyinDownloader.is_user_profile_url(request.url):
            import time
            start_time = time.time()

            # 使用流式下载以获取完整的统计信息
            summary_data = None
            failed_videos = []

            async for event in service.download_user_videos_stream(
                user_url=request.url,
                output_dir=output_dir,
                quality=request.quality.value,
            ):
                if event.get("type") == "done":
                    summary_data = event
                elif event.get("type") == "error":
                    raise DownloaderError(url=request.url, message=event.get("message", "下载失败"))

            if not summary_data:
                raise DownloaderError(url=request.url, message="下载过程异常终止")

            # 构建包含完整统计的响应
            return {
                "success": True,
                "message": f"下载完成：新下载 {summary_data.get('succeeded', 0)} 个，跳过 {summary_data.get('skipped', 0)} 个，失败 {summary_data.get('failed', 0)} 个",
                "summary": {
                    "username": summary_data.get("username", ""),
                    "video_count": summary_data.get("total", 0),
                    "work_count": summary_data.get("work_count", 0),
                    "non_video_count": summary_data.get("non_video_count", 0),
                    "succeeded": summary_data.get("succeeded", 0),
                    "skipped": summary_data.get("skipped", 0),
                    "failed": summary_data.get("failed", 0),
                    "failed_videos": summary_data.get("skipped_videos", []),  # 这里是失败列表
                    "elapsed_time": summary_data.get("elapsed_time", 0),
                    "folder_path": summary_data.get("folder_path", ""),
                },
            }

        result = await service.download(
            url=request.url,
            output_dir=output_dir,
            quality=request.quality.value,
            audio_only=request.audio_only,
        )

        if result.success:
            return DownloadResponse(
                success=True,
                message="下载成功" + ("（含字幕）" if result.subtitle_path else ""),
                video_info=VideoInfoResponse(
                    url=result.video_info.url,
                    platform=result.video_info.platform.name,
                    video_id=result.video_info.video_id,
                    title=result.video_info.title,
                    author=result.video_info.author,
                    duration=result.video_info.duration,
                    thumbnail=result.video_info.thumbnail,
                    available_qualities=result.video_info.available_qualities,
                ),
                file_path=str(result.file_path) if result.file_path else None,
                file_size=result.file_size,
                file_size_human=result.file_size_human,
                elapsed_time=result.elapsed_time,
                subtitle_path=str(result.subtitle_path) if result.subtitle_path else None,
            )
        else:
            return DownloadResponse(
                success=False,
                message=result.error_message or "下载失败",
            )

    except UnsupportedPlatformError as e:
        raise HTTPException(status_code=400, detail=f"不支持的平台: {e.url}")
    except DownloaderError as e:
        raise HTTPException(status_code=400, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/download/user-stream",
    summary="流式下载用户主页视频",
)
async def download_user_stream(request: DownloadRequest):
    """
    流式下载抖音用户主页所有视频，返回 SSE 事件流。
    每下载完一个视频就推送一个事件，前端可实时显示进度。
    """
    import json
    from src.downloaders.douyin import DouyinDownloader

    if not DouyinDownloader.is_user_profile_url(request.url):
        raise HTTPException(status_code=400, detail="此接口仅支持用户主页URL")

    service = get_service()
    output_dir = _resolve_output_dir(request)

    async def event_generator():
        try:
            async for event in service.download_user_videos_stream(
                user_url=request.url,
                output_dir=output_dir,
                quality=request.quality.value,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post(
    "/download/async",
    response_model=DownloadProgressResponse,
    summary="异步下载视频",
)
async def download_video_async(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
):
    """
    异步下载视频，返回任务ID用于查询进度
    """
    task_id = str(uuid4())

    # 初始化任务状态
    download_tasks[task_id] = {
        "status": "pending",
        "progress": 0,
        "speed": None,
        "eta": None,
        "error": None,
        "result": None,
    }

    # 后台执行下载
    background_tasks.add_task(
        _execute_download,
        task_id,
        request.url,
        request.quality.value,
        request.audio_only,
    )

    return DownloadProgressResponse(
        task_id=task_id,
        status="pending",
        progress=0,
    )


async def _execute_download(
    task_id: str,
    url: str,
    quality: str,
    audio_only: bool,
):
    """后台执行下载任务"""
    service = get_service()
    settings = get_settings()

    try:
        download_tasks[task_id]["status"] = "downloading"

        result = await service.download(
            url=url,
            output_dir=settings.download.output_dir,
            quality=quality,
            audio_only=audio_only,
        )

        if result.success:
            download_tasks[task_id].update({
                "status": "completed",
                "progress": 100,
                "result": {
                    "file_path": str(result.file_path),
                    "file_size": result.file_size,
                    "subtitle_path": str(result.subtitle_path) if result.subtitle_path else None,
                },
            })
        else:
            download_tasks[task_id].update({
                "status": "failed",
                "error": result.error_message,
            })

    except Exception as e:
        download_tasks[task_id].update({
            "status": "failed",
            "error": str(e),
        })


@router.get(
    "/download/status/{task_id}",
    response_model=DownloadProgressResponse,
    summary="查询下载进度",
)
async def get_download_status(task_id: str):
    """查询异步下载任务的进度"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = download_tasks[task_id]
    return DownloadProgressResponse(
        task_id=task_id,
        status=task["status"],
        progress=task["progress"],
        speed=task.get("speed"),
        eta=task.get("eta"),
        error=task.get("error"),
    )


@router.get(
    "/download/file/{task_id}",
    summary="获取已下载的文件",
)
async def get_downloaded_file(task_id: str):
    """下载完成后获取文件"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    task = download_tasks[task_id]

    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="下载尚未完成")

    file_path = Path(task["result"]["file_path"])

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type="application/octet-stream",
    )


@router.post(
    "/validate",
    summary="验证URL是否支持",
)
async def validate_url(request: VideoInfoRequest):
    """检查URL是否受支持"""
    service = get_service()
    is_supported = service.is_url_supported(request.url)

    return {
        "url": request.url,
        "supported": is_supported,
    }


@router.post(
    "/extract-audio",
    summary="从视频提取音频",
)
async def extract_audio(
    file_path: str,
    format: str = "mp3",
    bitrate: str = "192k",
):
    """
    从视频文件提取音频

    - file_path: 视频文件路径
    - format: 输出格式 (mp3, aac, wav, flac)
    - bitrate: 比特率 (128k, 192k, 256k, 320k)
    """
    from src.services.audio_extractor import AudioExtractor

    video_path = Path(file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail=f"文件不存在: {file_path}")

    extractor = AudioExtractor()

    try:
        output_path = await extractor.extract_audio(
            video_path=video_path,
            format=format,
            bitrate=bitrate,
        )

        return {
            "success": True,
            "message": "音频提取成功",
            "input_file": str(video_path),
            "output_file": str(output_path),
            "format": format,
            "bitrate": bitrate,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
