"""
语音转文字服务 - ASR (faster-whisper)
独立服务模块，支持模型下载进度显示
"""

import json
import asyncio
import threading
from pathlib import Path
from typing import Optional, AsyncGenerator, Callable
from datetime import timedelta
from queue import Queue

from config import (
    WHISPER_MODEL,
    WHISPER_MODEL_REPO,
    WHISPER_MODEL_PATH,
    MODELS_DIR,
    DEVICE,
    COMPUTE_TYPE,
    OUTPUT_FORMAT,
    DOWNLOADS_DIR,
)


# 全局模型实例
_model_instance = None
_model_lock = threading.Lock()


def reset_model():
    """重置模型实例（切换设备时调用）"""
    global _model_instance
    with _model_lock:
        _model_instance = None
        print("[ASR] 模型已重置，下次使用时将重新加载")


def check_model_exists() -> dict:
    """检查模型是否已下载"""
    model_path = WHISPER_MODEL_PATH

    if model_path.exists():
        # 检查关键文件
        required_files = ["model.bin", "config.json"]
        missing = [f for f in required_files if not (model_path / f).exists()]

        if not missing:
            # 计算模型大小
            total_size = sum(f.stat().st_size for f in model_path.glob("*") if f.is_file())
            return {
                "exists": True,
                "path": str(model_path),
                "size_mb": round(total_size / (1024 * 1024), 2),
                "model_name": WHISPER_MODEL,
            }

    return {
        "exists": False,
        "path": str(model_path),
        "model_name": WHISPER_MODEL,
        "repo": WHISPER_MODEL_REPO,
    }


async def download_model_stream() -> AsyncGenerator[dict, None]:
    """
    下载模型，流式返回进度

    Yields:
        下载进度事件
    """
    from huggingface_hub import snapshot_download, HfFileSystem
    from huggingface_hub.utils import tqdm as hf_tqdm

    yield {
        "type": "start",
        "message": f"开始下载模型: {WHISPER_MODEL_REPO}",
        "model_name": WHISPER_MODEL,
    }

    # 先获取模型文件列表和总大小
    try:
        yield {"type": "progress", "status": "checking", "message": "正在获取模型信息..."}

        fs = HfFileSystem()
        files = fs.ls(WHISPER_MODEL_REPO, detail=True)
        total_size = sum(f.get("size", 0) for f in files if f.get("type") == "file")
        total_size_mb = round(total_size / (1024 * 1024), 2)

        yield {
            "type": "progress",
            "status": "info",
            "message": f"模型大小: {total_size_mb} MB",
            "total_size_mb": total_size_mb,
        }

    except Exception as e:
        yield {"type": "progress", "status": "info", "message": f"无法获取模型大小: {e}"}
        total_size_mb = 0

    # 使用队列在线程间传递进度
    progress_queue: Queue = Queue()
    download_complete = threading.Event()
    download_error = {"error": None}

    def download_in_thread():
        """在线程中执行下载"""
        try:
            # 自定义进度回调
            downloaded = 0
            last_percent = -1

            def progress_callback(progress):
                nonlocal downloaded, last_percent
                if hasattr(progress, 'n'):
                    downloaded = progress.n
                    total = progress.total or 1
                    percent = int(downloaded / total * 100)
                    if percent != last_percent:
                        last_percent = percent
                        progress_queue.put({
                            "type": "progress",
                            "status": "downloading",
                            "percent": percent,
                            "downloaded_mb": round(downloaded / (1024 * 1024), 2),
                            "message": f"下载中... {percent}%",
                        })

            # 下载模型
            snapshot_download(
                WHISPER_MODEL_REPO,
                local_dir=str(WHISPER_MODEL_PATH),
                local_dir_use_symlinks=False,
            )

            progress_queue.put({
                "type": "done",
                "message": "模型下载完成",
            })

        except Exception as e:
            download_error["error"] = str(e)
            progress_queue.put({
                "type": "error",
                "message": str(e),
            })

        finally:
            download_complete.set()

    # 启动下载线程
    thread = threading.Thread(target=download_in_thread, daemon=True)
    thread.start()

    # 发送进度更新
    while not download_complete.is_set() or not progress_queue.empty():
        try:
            event = progress_queue.get(timeout=0.5)
            yield event
            if event.get("type") in ("done", "error"):
                break
        except Exception:
            # 队列超时，发送心跳
            yield {"type": "heartbeat", "message": "下载中..."}

    # 等待线程结束
    thread.join(timeout=5)


def get_model():
    """获取或加载模型实例（单例）"""
    global _model_instance

    with _model_lock:
        if _model_instance is None:
            from faster_whisper import WhisperModel

            model_path = WHISPER_MODEL_PATH
            if not model_path.exists():
                raise RuntimeError("模型未下载，请先下载模型")

            print(f"[ASR] 正在加载模型: {model_path}")
            _model_instance = WhisperModel(
                str(model_path),
                device=DEVICE,
                compute_type=COMPUTE_TYPE,
            )
            print(f"[ASR] 模型加载完成 (设备: {DEVICE})")

        return _model_instance


def transcribe_single_file(
    audio_path: Path,
    language: str = "zh",
    output_format: str = OUTPUT_FORMAT,
) -> dict:
    """
    转写单个音频文件

    Args:
        audio_path: 音频文件路径
        language: 语言代码
        output_format: 输出格式

    Returns:
        转写结果
    """
    audio_path = Path(audio_path)

    if not audio_path.exists():
        return {
            "success": False,
            "file": str(audio_path),
            "error": "文件不存在",
        }

    try:
        model = get_model()

        # 执行转写
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        # 收集结果
        result_segments = []
        full_text = []

        for segment in segments:
            result_segments.append({
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
            })
            full_text.append(segment.text.strip())

        text = " ".join(full_text)

        # 保存输出文件
        output_files = _save_outputs(audio_path, text, result_segments, output_format)

        return {
            "success": True,
            "file": str(audio_path),
            "language": info.language,
            "duration": round(info.duration, 1),
            "text_preview": text[:200] + "..." if len(text) > 200 else text,
            "text_length": len(text),
            "output_files": output_files,
        }

    except Exception as e:
        return {
            "success": False,
            "file": str(audio_path),
            "error": str(e),
        }


def _save_outputs(audio_path: Path, text: str, segments: list, output_format: str) -> dict:
    """保存输出文件"""
    output_files = {}
    base_path = audio_path.with_suffix("")

    formats = ["txt", "srt", "json"] if output_format == "all" else [output_format]

    for fmt in formats:
        try:
            if fmt == "txt":
                txt_path = base_path.with_suffix(".txt")
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(text)
                output_files["txt"] = str(txt_path)

            elif fmt == "srt":
                srt_path = base_path.with_suffix(".srt")
                with open(srt_path, "w", encoding="utf-8") as f:
                    f.write(_to_srt(segments))
                output_files["srt"] = str(srt_path)

            elif fmt == "json":
                json_path = base_path.with_suffix(".json")
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "text": text,
                        "segments": segments,
                    }, f, ensure_ascii=False, indent=2)
                output_files["json"] = str(json_path)

        except Exception as e:
            output_files[f"{fmt}_error"] = str(e)

    return output_files


def _to_srt(segments: list) -> str:
    """转换为 SRT 字幕格式"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg["start"])
        end = _format_srt_time(seg["end"])
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(seg["text"])
        lines.append("")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """格式化时间为 SRT 格式"""
    td = timedelta(seconds=seconds)
    hours, remainder = divmod(int(td.total_seconds()), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int((td.total_seconds() % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


async def transcribe_folder_stream(
    folder_path: Path,
    language: str = "zh",
    skip_existing: bool = True,
) -> AsyncGenerator[dict, None]:
    """
    流式转写文件夹中的所有音频文件

    Args:
        folder_path: 文件夹路径
        language: 语言
        skip_existing: 是否跳过已存在的 txt

    Yields:
        进度事件
    """
    folder_path = Path(folder_path)

    if not folder_path.exists():
        yield {"type": "error", "message": "文件夹不存在"}
        return

    # 检查模型
    model_status = check_model_exists()
    if not model_status["exists"]:
        yield {"type": "error", "message": "模型未下载，请先下载模型"}
        return

    # 获取所有音频文件
    audio_files = []
    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        audio_files.extend(folder_path.glob(ext))

    # 过滤掉以 _ 开头的文件
    audio_files = sorted([f for f in audio_files if not f.name.startswith("_")])

    if not audio_files:
        yield {"type": "done", "message": "没有找到音频文件", "total": 0, "transcribed": 0, "skipped": 0, "failed": 0}
        return

    total = len(audio_files)
    transcribed = 0
    skipped = 0
    failed = 0

    yield {
        "type": "start",
        "total": total,
        "message": f"开始转写 {total} 个音频文件",
    }

    # 预加载模型
    yield {"type": "progress", "current": 0, "total": total, "status": "loading", "message": "正在加载模型..."}

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, get_model)
    except Exception as e:
        yield {"type": "error", "message": f"模型加载失败: {e}"}
        return

    yield {"type": "progress", "current": 0, "total": total, "status": "ready", "message": "模型加载完成"}

    for i, audio_file in enumerate(audio_files, 1):
        txt_path = audio_file.with_suffix(".txt")

        # 检查是否已存在
        if skip_existing and txt_path.exists():
            skipped += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": audio_file.name,
                "status": "skipped",
                "message": "已存在，跳过",
            }
            continue

        # 发送处理中状态
        yield {
            "type": "progress",
            "current": i,
            "total": total,
            "file": audio_file.name,
            "status": "processing",
            "message": "转写中...",
        }

        # 在线程池中执行转写
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            transcribe_single_file,
            audio_file,
            language,
        )

        if result["success"]:
            transcribed += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": audio_file.name,
                "status": "done",
                "message": f"完成 ({result.get('text_length', 0)} 字)",
                "preview": result.get("text_preview", ""),
            }
        else:
            failed += 1
            yield {
                "type": "progress",
                "current": i,
                "total": total,
                "file": audio_file.name,
                "status": "error",
                "message": result.get("error", "转写失败")[:50],
            }

    yield {
        "type": "done",
        "total": total,
        "transcribed": transcribed,
        "skipped": skipped,
        "failed": failed,
        "message": f"转写完成: 成功 {transcribed}, 跳过 {skipped}, 失败 {failed}",
    }


def get_folder_stats(folder_name: str) -> dict:
    """获取文件夹的转写统计"""
    folder_path = DOWNLOADS_DIR / folder_name

    if not folder_path.exists():
        return {"exists": False}

    audio_files = []
    for ext in ["*.mp3", "*.wav", "*.m4a"]:
        audio_files.extend(f for f in folder_path.glob(ext) if not f.name.startswith("_"))

    txt_files = [f for f in folder_path.glob("*.txt") if not f.name.startswith("_")]

    # 检查哪些还没转写
    audio_names = {f.stem for f in audio_files}
    txt_names = {f.stem for f in txt_files}
    pending = audio_names - txt_names

    return {
        "exists": True,
        "audio_count": len(audio_files),
        "text_count": len(txt_files),
        "pending_count": len(pending),
        "pending_files": list(pending)[:10],
    }


if __name__ == "__main__":
    print("语音转文字服务模块")
    print(f"模型: {WHISPER_MODEL}")
    print(f"设备: {DEVICE}")
    status = check_model_exists()
    print(f"模型状态: {'已下载' if status['exists'] else '未下载'}")
