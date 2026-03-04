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

# 标记文件名：记录已完成人声分离的文件
_VOCAL_SEP_MARKER = "_vocal_separated.json"


def _load_separated_set(folder_path: Path) -> set:
    """读取该文件夹已完成人声分离的文件名集合"""
    marker = folder_path / _VOCAL_SEP_MARKER
    if marker.exists():
        try:
            return set(json.loads(marker.read_text(encoding="utf-8")))
        except Exception:
            pass
    return set()


def _save_separated_set(folder_path: Path, names: set):
    """保存已完成人声分离的文件名集合"""
    marker = folder_path / _VOCAL_SEP_MARKER
    marker.write_text(json.dumps(sorted(names), ensure_ascii=False), encoding="utf-8")


def _extract_ffmpeg_error(stderr_bytes: bytes) -> str:
    """从 ffmpeg stderr 中提取有意义的错误信息（跳过版本头）"""
    try:
        text = stderr_bytes.decode("utf-8", errors="ignore")
    except Exception:
        return "FFmpeg 转换失败"

    # ffmpeg stderr 的有用错误通常在最后几行
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    # 取最后 3 行非空内容
    tail = lines[-3:] if len(lines) > 3 else lines
    return " | ".join(tail)[:200] if tail else "FFmpeg 转换失败（无输出）"


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
    vocal_separation: bool = False,
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

    try:
        # 如果 MP3 已存在，跳过 ffmpeg 转换（仅在需要人声分离时继续）
        if not output_path.exists():
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

            # Windows 下隐藏控制台窗口，使用 bytes 模式避免编码问题
            creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0

            result = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=creationflags,
            )

            if result.returncode != 0:
                return {
                    "success": False,
                    "input": str(input_path),
                    "error": _extract_ffmpeg_error(result.stderr),
                }

        # 人声分离（可选）
        if vocal_separation:
            from vocal_separator import separate_vocals
            sep_result = separate_vocals(output_path)
            if not sep_result["success"]:
                return {
                    "success": False,
                    "input": str(input_path),
                    "error": sep_result["message"],
                }

        return {
            "success": True,
            "input": str(input_path),
            "output": str(output_path),
            "size_mb": round(output_path.stat().st_size / (1024 * 1024), 2),
            "vocal_separated": vocal_separation,
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
    vocal_separation: bool = False,
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

    # 加载已完成人声分离的记录
    separated_set = _load_separated_set(folder_path) if vocal_separation else set()

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

        # 跳过逻辑
        if skip_existing and mp3_path.exists():
            if not vocal_separation or mp4_file.stem in separated_set:
                skipped += 1
                yield {
                    "type": "progress",
                    "current": i,
                    "total": total,
                    "file": mp4_file.name,
                    "status": "skipped",
                    "message": "已存在，跳过" + ("（已分离）" if vocal_separation else ""),
                }
                continue

        # 发送处理中状态
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "file": mp4_file.name,
            "status": "processing",
            "message": "转换中..." + (" (含人声分离)" if vocal_separation else ""),
        }

        # 在线程池中执行转换（人声分离时加 5 分钟超时，防止卡死）
        loop = asyncio.get_event_loop()
        timeout = 300 if vocal_separation else 120
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda mp4=mp4_file, mp3=mp3_path: convert_single_file(
                        mp4, mp3, vocal_separation=vocal_separation,
                    ),
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            failed += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": mp4_file.name,
                "status": "error",
                "message": f"处理超时（>{timeout}s），已跳过",
            }
            continue

        if result["success"]:
            converted += 1
            # 记录已完成人声分离
            if vocal_separation:
                separated_set.add(mp4_file.stem)
                _save_separated_set(folder_path, separated_set)
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
                "message": result.get("error", "转换失败")[:100],
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


def check_mp4_valid(file_path: Path) -> bool:
    """用 ffprobe 检测 MP4 文件是否可读"""
    try:
        cmd = [
            FFMPEG_PATH.replace("ffmpeg", "ffprobe") if "ffmpeg" in FFMPEG_PATH else "ffprobe",
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_name",
            "-of", "csv=p=0",
            str(file_path),
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
        result = subprocess.run(cmd, capture_output=True, timeout=10, creationflags=creationflags)
        return result.returncode == 0
    except Exception:
        return False


async def cleanup_bad_mp4s_stream(folder_path: Path) -> AsyncGenerator[dict, None]:
    """扫描并删除损坏的 MP4 文件（流式返回进度）"""
    folder_path = Path(folder_path)
    if not folder_path.exists():
        yield {"type": "error", "message": "文件夹不存在"}
        return

    mp4_files = sorted(f for f in folder_path.glob("*.mp4") if not f.name.startswith("_"))
    if not mp4_files:
        yield {"type": "done", "message": "没有 MP4 文件", "total": 0, "bad": 0}
        return

    total = len(mp4_files)
    bad_files = []

    yield {"type": "start", "total": total, "message": f"正在检测 {total} 个 MP4 文件..."}

    loop = asyncio.get_event_loop()
    for i, mp4 in enumerate(mp4_files, 1):
        valid = await loop.run_in_executor(None, check_mp4_valid, mp4)
        if not valid:
            bad_files.append(mp4)
            # 删除坏 MP4 及其对应的空 MP3（如果有）
            mp3 = mp4.with_suffix(".mp3")
            mp4.unlink(missing_ok=True)
            if mp3.exists():
                mp3.unlink(missing_ok=True)
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": mp4.name,
                "status": "deleted",
                "message": "损坏，已删除",
            }
        else:
            if i % 50 == 0:
                yield {
                    "type": "progress",
                    "current": i,
                    "total": total,
                    "file": mp4.name,
                    "status": "ok",
                    "message": f"已检测 {i}/{total}",
                }

    yield {
        "type": "done",
        "total": total,
        "bad": len(bad_files),
        "bad_files": [f.name for f in bad_files],
        "message": f"检测完成: {len(bad_files)} 个损坏文件已删除，可重新下载补回",
    }


if __name__ == "__main__":
    print("音频转换服务模块")
    print(f"FFmpeg 可用: {check_ffmpeg()}")
