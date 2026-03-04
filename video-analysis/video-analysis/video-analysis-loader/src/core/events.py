"""
SSE 事件标准定义 — 用户主页批量下载的流式事件工厂

所有实现 IUserProfileDownloader 的下载器都应使用这些工厂函数生成事件，
以保证前端 StreamEvent 类型契约的一致性。
"""

# 事件类型常量
EVENT_EXTRACTING = "extracting"
EVENT_EXTRACTED = "extracted"
EVENT_DOWNLOADING = "downloading"
EVENT_DOWNLOADED = "downloaded"
EVENT_RETRYING = "retrying"
EVENT_DONE = "done"
EVENT_ERROR = "error"


def make_extracting_event(message: str) -> dict:
    return {"type": EVENT_EXTRACTING, "message": message}


def make_extracted_event(
    total: int,
    work_count: int = 0,
    non_video_count: int = 0,
    message: str = "",
) -> dict:
    return {
        "type": EVENT_EXTRACTED,
        "total": total,
        "work_count": work_count,
        "non_video_count": non_video_count,
        "message": message or f"找到 {total} 个视频",
    }


def make_downloading_event(
    index: int,
    total: int,
    url: str,
    title: str,
    succeeded_so_far: int = 0,
    remaining: int = 0,
    is_retry: bool = False,
    retry_round: int = 0,
) -> dict:
    event = {
        "type": EVENT_DOWNLOADING,
        "index": index,
        "total": total,
        "url": url,
        "title": title,
        "succeeded_so_far": succeeded_so_far,
        "remaining": remaining,
    }
    if is_retry:
        event["is_retry"] = True
        event["retry_round"] = retry_round
    return event


def make_downloaded_event(
    index: int,
    total: int,
    title: str,
    success: bool,
    file_path: str = None,
    file_size_human: str = None,
    has_subtitle: bool = False,
    error: str = None,
    skipped: bool = False,
    skipped_count: int = None,
    permanently_failed: bool = False,
    succeeded_so_far: int = None,
    remaining: int = None,
    url: str = None,
    is_retry: bool = False,
    retry_round: int = 0,
) -> dict:
    event = {
        "type": EVENT_DOWNLOADED,
        "index": index,
        "total": total,
        "title": title,
        "success": success,
    }
    if file_path:
        event["file_path"] = file_path
    if file_size_human:
        event["file_size_human"] = file_size_human
    if has_subtitle:
        event["has_subtitle"] = has_subtitle
    if error:
        event["error"] = error
    if skipped:
        event["skipped"] = True
    if skipped_count is not None:
        event["skipped_count"] = skipped_count
    if permanently_failed:
        event["permanently_failed"] = True
    if succeeded_so_far is not None:
        event["succeeded_so_far"] = succeeded_so_far
    if remaining is not None:
        event["remaining"] = remaining
    if url:
        event["url"] = url
    if is_retry:
        event["is_retry"] = True
        event["retry_round"] = retry_round
    return event


def make_retrying_event(
    round_num: int,
    max_rounds: int,
    failed_count: int,
    message: str = "",
) -> dict:
    return {
        "type": EVENT_RETRYING,
        "round": round_num,
        "max_rounds": max_rounds,
        "failed_count": failed_count,
        "message": message or f"开始第 {round_num} 轮重试，共 {failed_count} 个失败视频...",
    }


def make_done_event(
    total: int,
    work_count: int,
    non_video_count: int,
    succeeded: int,
    skipped: int,
    failed: int,
    skipped_videos: list,
    elapsed_time: float,
    folder_path: str,
    username: str,
) -> dict:
    return {
        "type": EVENT_DONE,
        "total": total,
        "work_count": work_count,
        "non_video_count": non_video_count,
        "succeeded": succeeded,
        "skipped": skipped,
        "failed": failed,
        "skipped_videos": skipped_videos,
        "elapsed_time": elapsed_time,
        "folder_path": folder_path,
        "username": username,
    }


def make_error_event(message: str) -> dict:
    return {"type": EVENT_ERROR, "message": message}
