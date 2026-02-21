"""
音频转换服务 - MP4 转 MP3
独立服务模块
"""

import subprocess
import asyncio
import json
from pathlib import Path
from typing import Optional, AsyncGenerator

from config import FFMPEG_PATH, MP3_BITRATE, DOWNLOADS_DIR


def check_ffmpeg() -> bool:
    """检查 FFmpeg 是否可用"""
    try:
        result = subprocess.run(
            [FFMPEG_PATH, "-version"],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def convert_single_file(
    input_path: Path,
    output_path: Optional[Path] = None,
    bitrate: str = MP3_BITRATE,
) -> dict:
    """
    将单个 MP4 文件转换为 MP3

    Args:
        input_path: 输入 MP4 文件路径
        output_path: 输出 MP3 文件路径
        bitrate: MP3 比特率

    Returns:
        转换结果字典
    """
    input_path = Path(input_path)

    if not input_path.exists():
        return {
            "success": False,
            "input": str(input_path),
            "error": "文件不存在",
        }

    if output_path is None:
        output_path = input_path.with_suffix(".mp3")
    else:
        output_path = Path(output_path)

    # 确保输出目录存在
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # FFmpeg 命令
    cmd = [
        FFMPEG_PATH,
        "-i", str(input_path),
        "-vn",  # 不要视频
        "-acodec", "libmp3lame",
        "-ab", bitrate,
        "-ar", "44100",  # 采样率
        "-y",  # 覆盖输出文件
        str(output_path),
    ]

    try:
        # Windows 下隐藏控制台窗口，使用 bytes 模式避免编码问题
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

        result = subprocess.run(
            cmd,
            capture_output=True,
            creationflags=creationflags,
        )

        if result.returncode != 0:
            # 尝试解码错误信息
            try:
                error_msg = result.stderr.decode('utf-8', errors='ignore')
            except Exception:
                error_msg = "FFmpeg 转换失败"

            return {
                "success": False,
                "input": str(input_path),
                "error": error_msg[:200],
            }

        return {
            "success": True,
            "input": str(input_path),
            "output": str(output_path),
            "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
        }

    except Exception as e:
        return {
            "success": False,
            "input": str(input_path),
            "error": str(e),
        }


async def convert_folder_stream(
    folder_path: Path,
    skip_existing: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    流式转换文件夹中的所有 MP4 文件

    Args:
        folder_path: 文件夹路径
        skip_existing: 是否跳过已存在的 MP3

    Yields:
        进度事件
    """
    folder_path = Path(folder_path)

    if not folder_path.exists():
        yield {"type": "error", "message": "文件夹不存在"}
        return

    # 获取所有 MP4 文件
    mp4_files = sorted(folder_path.glob("*.mp4"))

    # 过滤掉以 _ 开头的文件
    mp4_files = [f for f in mp4_files if not f.name.startswith("_")]

    if not mp4_files:
        yield {"type": "done", "message": "没有找到 MP4 文件", "total": 0, "converted": 0, "skipped": 0, "failed": 0}
        return

    total = len(mp4_files)
    converted = 0
    skipped = 0
    failed = 0

    yield {
        "type": "start",
        "total": total,
        "message": f"开始转换 {total} 个视频文件",
    }

    for i, mp4_file in enumerate(mp4_files, 1):
        mp3_path = mp4_file.with_suffix(".mp3")

        # 检查是否已存在
        if skip_existing and mp3_path.exists():
            skipped += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": mp4_file.name,
                "status": "skipped",
                "message": "已存在，跳过",
            }
            continue

        # 发送处理中状态
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "file": mp4_file.name,
            "status": "processing",
            "message": "转换中...",
        }

        # 在线程池中执行转换
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            convert_single_file,
            mp4_file,
            mp3_path,
        )

        if result["success"]:
            converted += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": mp4_file.name,
                "status": "done",
                "message": f"完成 ({result.get('size_mb', 0)} MB)",
            }
        else:
            failed += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": mp4_file.name,
                "status": "error",
                "message": result.get("error", "转换失败")[:50],
            }

    yield {
        "type": "done",
        "total": total,
        "converted": converted,
        "skipped": skipped,
        "failed": failed,
        "message": f"转换完成: 成功 {converted}, 跳过 {skipped}, 失败 {failed}",
    }


def get_folder_stats(folder_name: str) -> dict:
    """获取文件夹的转换统计"""
    folder_path = DOWNLOADS_DIR / folder_name

    if not folder_path.exists():
        return {"exists": False}

    mp4_files = [f for f in folder_path.glob("*.mp4") if not f.name.startswith("_")]
    mp3_files = [f for f in folder_path.glob("*.mp3") if not f.name.startswith("_")]

    # 检查哪些还没转换
    mp4_names = {f.stem for f in mp4_files}
    mp3_names = {f.stem for f in mp3_files}
    pending = mp4_names - mp3_names

    return {
        "exists": True,
        "video_count": len(mp4_files),
        "audio_count": len(mp3_files),
        "pending_count": len(pending),
        "pending_files": list(pending)[:10],  # 只返回前10个
    }


if __name__ == "__main__":
    print("音频转换服务模块")
    print(f"FFmpeg 可用: {check_ffmpeg()}")
