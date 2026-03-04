"""
数据清洗 API 服务
分离 MP4转MP3 和 ASR转文字 两个功能
"""

import json
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import config
from config import DOWNLOADS_DIR, MODELS_DIR, WHISPER_MODEL
from converter_service import (
    check_ffmpeg,
    convert_folder_stream,
    cleanup_bad_mp4s_stream,
    get_folder_stats as get_converter_stats,
)
from transcriber_service import (
    check_model_exists,
    download_model_stream,
    transcribe_folder_stream,
    get_folder_stats as get_transcriber_stats,
    reset_model,
)


app = FastAPI(
    title="Video Analysis Cleaner API",
    description="视频数据清洗服务 - MP4转MP3、语音转文字",
    version="2.0.0",
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# 请求模型
# ============================================================

class ConvertRequest(BaseModel):
    """音频转换请求"""
    folder_name: str
    skip_existing: bool = True
    vocal_separation: bool = False


class TranscribeRequest(BaseModel):
    """转写请求"""
    folder_name: str
    language: str = "zh"
    skip_existing: bool = True


class DeviceConfigRequest(BaseModel):
    """设备配置请求"""
    device: str  # "cuda" 或 "cpu"


# ============================================================
# 通用接口
# ============================================================

@app.get("/api/cleaner/status")
async def get_status():
    """获取服务状态"""
    model_status = check_model_exists()

    return {
        "status": "running",
        "ffmpeg_available": check_ffmpeg(),
        "model": {
            "name": WHISPER_MODEL,
            "exists": model_status["exists"],
            "path": str(MODELS_DIR),
            "size_mb": model_status.get("size_mb", 0),
        },
        "gpu": {
            "available": config.GPU_AVAILABLE,
            "name": config.GPU_NAME,
            "error": config.GPU_ERROR,
        },
        "device": config.DEVICE,
        "compute_type": config.COMPUTE_TYPE,
        "downloads_dir": str(DOWNLOADS_DIR),
        "paths": {
            "downloads_dir": str(DOWNLOADS_DIR),
            "models_dir": str(MODELS_DIR),
        },
    }


@app.post("/api/cleaner/device")
async def set_device(request: DeviceConfigRequest):
    """切换设备 (GPU/CPU)"""
    if request.device not in ["cuda", "cpu"]:
        raise HTTPException(status_code=400, detail="设备必须是 'cuda' 或 'cpu'")

    if request.device == "cuda" and not config.GPU_AVAILABLE:
        raise HTTPException(
            status_code=400,
            detail=f"GPU 不可用: {config.GPU_ERROR or '未检测到 CUDA'}"
        )

    # 更新配置
    config.DEVICE = request.device
    config.COMPUTE_TYPE = "float16" if request.device == "cuda" else "int8"

    # 重置模型（下次使用时重新加载）
    reset_model()

    return {
        "success": True,
        "device": config.DEVICE,
        "compute_type": config.COMPUTE_TYPE,
        "message": f"已切换到 {'GPU' if request.device == 'cuda' else 'CPU'} 模式",
    }


@app.get("/api/cleaner/folders")
async def list_folders():
    """列出 downloads 目录下的所有用户文件夹"""
    if not DOWNLOADS_DIR.exists():
        return {"folders": []}

    folders = []

    for folder in DOWNLOADS_DIR.iterdir():
        if folder.is_dir() and not folder.name.startswith("_"):
            # 统计文件数量
            mp4_files = [f for f in folder.glob("*.mp4") if not f.name.startswith("_")]
            mp3_files = [f for f in folder.glob("*.mp3") if not f.name.startswith("_")]
            txt_files = [f for f in folder.glob("*.txt") if not f.name.startswith("_")]

            # 计算总大小
            total_size = sum(f.stat().st_size for f in folder.glob("*") if f.is_file())
            total_size_mb = round(total_size / (1024 * 1024), 2)

            # 最后修改时间
            try:
                last_modified = datetime.fromtimestamp(folder.stat().st_mtime).isoformat()
            except Exception:
                last_modified = ""

            folders.append({
                "name": folder.name,
                "path": str(folder),
                "video_count": len(mp4_files),
                "audio_count": len(mp3_files),
                "text_count": len(txt_files),
                "total_size_mb": total_size_mb,
                "last_modified": last_modified,
            })

    # 按修改时间排序
    folders.sort(key=lambda x: x["last_modified"], reverse=True)

    return {"folders": folders}


# ============================================================
# 模型管理接口
# ============================================================

@app.get("/api/cleaner/model/status")
async def get_model_status():
    """获取模型状态"""
    return check_model_exists()


@app.post("/api/cleaner/model/download")
async def download_model():
    """下载模型（流式返回进度）"""
    model_status = check_model_exists()

    if model_status["exists"]:
        return {"message": "模型已存在", "status": model_status}

    async def generate():
        async for event in download_model_stream():
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# MP4 转 MP3 接口
# ============================================================

@app.get("/api/cleaner/convert/stats/{folder_name}")
async def get_convert_stats(folder_name: str):
    """获取文件夹的转换统计"""
    stats = get_converter_stats(folder_name)
    if not stats.get("exists"):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return stats


@app.post("/api/cleaner/convert")
async def convert_folder(request: ConvertRequest):
    """
    转换文件夹中的 MP4 到 MP3（流式返回进度）
    """
    folder_path = DOWNLOADS_DIR / request.folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    if not check_ffmpeg():
        raise HTTPException(status_code=500, detail="FFmpeg 不可用")

    async def generate():
        async for event in convert_folder_stream(folder_path, request.skip_existing, request.vocal_separation):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 损坏文件清理接口
# ============================================================

@app.post("/api/cleaner/cleanup/{folder_name}")
async def cleanup_bad_mp4s(folder_name: str):
    """检测并删除损坏的 MP4 文件（流式返回进度）"""
    folder_path = DOWNLOADS_DIR / folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    async def generate():
        async for event in cleanup_bad_mp4s_stream(folder_path):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# ASR 语音转文字接口
# ============================================================

@app.get("/api/cleaner/transcribe/stats/{folder_name}")
async def get_transcribe_stats(folder_name: str):
    """获取文件夹的转写统计"""
    stats = get_transcriber_stats(folder_name)
    if not stats.get("exists"):
        raise HTTPException(status_code=404, detail="文件夹不存在")
    return stats


@app.post("/api/cleaner/transcribe")
async def transcribe_folder(request: TranscribeRequest):
    """
    转写文件夹中的音频文件（流式返回进度）
    """
    folder_path = DOWNLOADS_DIR / request.folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    model_status = check_model_exists()
    if not model_status["exists"]:
        raise HTTPException(status_code=400, detail="模型未下载，请先下载模型")

    async def generate():
        async for event in transcribe_folder_stream(
            folder_path,
            request.language,
            request.skip_existing,
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# 查看结果接口
# ============================================================

@app.get("/api/cleaner/folder/{folder_name}/files")
async def list_folder_files(folder_name: str):
    """列出指定文件夹中的文件"""
    folder_path = DOWNLOADS_DIR / folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    files = []
    for f in sorted(folder_path.glob("*")):
        if f.is_file() and not f.name.startswith("_"):
            files.append({
                "name": f.name,
                "path": str(f),
                "size_mb": round(f.stat().st_size / (1024 * 1024), 2),
                "extension": f.suffix.lower(),
                "has_mp3": f.with_suffix(".mp3").exists() if f.suffix.lower() == ".mp4" else None,
                "has_txt": f.with_suffix(".txt").exists() if f.suffix.lower() in [".mp4", ".mp3"] else None,
            })

    return {"folder": folder_name, "files": files}


@app.get("/api/cleaner/folder/{folder_name}/transcripts")
async def get_transcripts(folder_name: str):
    """获取文件夹中所有转写文本"""
    folder_path = DOWNLOADS_DIR / folder_name

    if not folder_path.exists():
        raise HTTPException(status_code=404, detail="文件夹不存在")

    transcripts = []

    for txt_file in sorted(folder_path.glob("*.txt")):
        if txt_file.name.startswith("_"):
            continue

        try:
            content = txt_file.read_text(encoding="utf-8")
            transcripts.append({
                "file": txt_file.stem,
                "content": content,
                "length": len(content),
            })
        except Exception:
            pass

    return {"folder": folder_name, "transcripts": transcripts}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
