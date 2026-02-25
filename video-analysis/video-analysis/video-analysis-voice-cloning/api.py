"""
Voice Cloning API 服务
"""

import asyncio
import json
import logging
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel

import config
from services.data_preparer import (
    get_blogger_source_data,
    get_dataset_info,
    prepare_dataset_stream,
)
from services.model_downloader import (
    check_pretrained_models,
    download_pretrained_stream,
    download_single_model_stream,
)
from services.trainer import (
    get_trained_model_info,
    train_model_stream,
)
from services.synthesizer import (
    get_synthesizer,
    synthesize_voice,
)
from services.emotion_manager import (
    get_emotion_types,
    get_reference_audios,
    tag_emotion,
    get_emotion_statistics,
    EMOTION_CATEGORIES,
)
from services.text_processor import (
    get_text_processor,
    preprocess_text,
    apply_preset,
    PRESETS,
)
from services.expression_library import (
    EXPRESSION_TYPES,
    EXPRESSION_CATEGORIES,
    load_library,
    extract_expression_clip,
    delete_expression_clip,
    get_library_stats,
    detect_expressions_in_text,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Video Analysis Voice Cloning API",
    description="声音克隆服务 - GPT-SoVITS",
    version="1.0.0",
)

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

class PrepareRequest(BaseModel):
    """数据准备请求"""
    blogger_name: str
    min_duration: float = 3.0
    max_duration: float = 15.0
    enable_denoise: bool = True  # 默认启用降噪


class TrainRequest(BaseModel):
    """训练请求"""
    blogger_name: str
    epochs_gpt: int = config.DEFAULT_EPOCHS_GPT
    epochs_sovits: int = config.DEFAULT_EPOCHS_SOVITS
    batch_size: int = config.DEFAULT_BATCH_SIZE


class SynthesizeRequest(BaseModel):
    """语音合成请求"""
    blogger_name: str
    text: str
    speed: float = 1.0
    emotion: str = None  # 情绪类型: neutral, happy, excited, serious, curious, sad, angry, gentle
    text_preset: str = "none"  # 文本预处理: strict, moderate, minimal, none (默认不处理)
    use_expressions: bool = True  # 是否使用表情库插入真实录音


class TagEmotionRequest(BaseModel):
    """情绪标注请求"""
    filename: str  # 音频文件名，如 "0001.wav"
    emotion: str   # 情绪类型


class TextPreviewRequest(BaseModel):
    """文本预处理预览请求"""
    text: str
    preset: str = "strict"  # strict, moderate, minimal, none


class ExtractExpressionRequest(BaseModel):
    """提取表情片段请求"""
    source_audio: str       # 源音频文件名 (如 "0001.wav")
    start_time: float       # 开始时间 (秒)
    end_time: float         # 结束时间 (秒)
    expression_type: str    # 表情类型
    text: str               # 对应文本


# ============================================================
# API 端点
# ============================================================

@app.get("/api/voice/status")
async def get_status():
    """获取服务状态"""
    pretrained = check_pretrained_models()
    synthesizer = get_synthesizer()

    return {
        "online": True,
        "gpu": {
            "available": config.GPU_AVAILABLE,
            "name": config.GPU_NAME,
            "memory_gb": config.GPU_MEMORY,
        },
        "device": config.DEVICE,
        "pretrained_models": pretrained,
        "synthesizer": synthesizer.get_status(),
        "paths": {
            "pretrained_dir": str(config.PRETRAINED_DIR),
            "trained_dir": str(config.TRAINED_DIR),
            "datasets_dir": str(config.DATASETS_DIR),
        },
    }


@app.get("/api/voice/bloggers")
async def list_bloggers():
    """列出所有博主及其状态"""
    bloggers = []

    # 从 downloads 目录获取所有博主
    if config.DOWNLOADS_DIR.exists():
        for d in config.DOWNLOADS_DIR.iterdir():
            if d.is_dir() and not d.name.startswith("."):
                blogger_name = d.name

                # 获取源数据信息
                source_data = get_blogger_source_data(blogger_name)

                # 获取数据集信息
                dataset = get_dataset_info(blogger_name)

                # 获取模型信息
                model = get_trained_model_info(blogger_name)

                bloggers.append({
                    "name": blogger_name,
                    "source": {
                        "has_data": source_data.get("total_pairs", 0) > 0,
                        "file_pairs": source_data.get("total_pairs", 0),
                    },
                    "dataset": {
                        "prepared": dataset.get("exists", False),
                        "segments": dataset.get("segment_count", 0),
                        "duration_minutes": dataset.get("total_duration_minutes", 0),
                    },
                    "model": {
                        "trained": model.get("ready", False),
                        "gpt_exists": model.get("models", {}).get("gpt", {}).get("exists", False),
                        "sovits_exists": model.get("models", {}).get("sovits", {}).get("exists", False),
                    },
                })

    return {"bloggers": bloggers}


@app.get("/api/voice/blogger/{blogger_name}")
async def get_blogger_detail(blogger_name: str):
    """获取博主详情"""
    source_data = get_blogger_source_data(blogger_name)
    dataset = get_dataset_info(blogger_name)
    model = get_trained_model_info(blogger_name)

    return {
        "name": blogger_name,
        "source": source_data,
        "dataset": dataset,
        "model": model,
    }


@app.get("/api/voice/models/status")
async def get_models_status():
    """获取预训练模型状态"""
    return check_pretrained_models()


@app.post("/api/voice/models/download")
async def download_models():
    """下载预训练模型 (流式)"""

    async def generate() -> AsyncGenerator[str, None]:
        for progress in download_pretrained_stream():
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/voice/models/download/{model_key}")
async def download_single_model(model_key: str):
    """下载单个预训练模型 (流式)"""

    async def generate() -> AsyncGenerator[str, None]:
        for progress in download_single_model_stream(model_key):
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/voice/prepare")
async def prepare_dataset(request: PrepareRequest):
    """准备训练数据 (流式)"""

    async def generate() -> AsyncGenerator[str, None]:
        for progress in prepare_dataset_stream(
            request.blogger_name,
            request.min_duration,
            request.max_duration,
            request.enable_denoise,
        ):
            yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/voice/train")
async def train_model(request: TrainRequest):
    """训练模型 (流式，包含 loss 数据)"""

    # 检查预训练模型
    pretrained = check_pretrained_models()
    if not pretrained["all_ready"]:
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'message': '请先下载预训练模型'})}\n\n"]),
            media_type="text/event-stream",
        )

    # 检查数据集
    dataset = get_dataset_info(request.blogger_name)
    if not dataset.get("exists"):
        return StreamingResponse(
            iter([f"data: {json.dumps({'type': 'error', 'message': '请先准备训练数据'})}\n\n"]),
            media_type="text/event-stream",
        )

    async def generate() -> AsyncGenerator[str, None]:
        try:
            for progress in train_model_stream(
                request.blogger_name,
                request.epochs_gpt,
                request.epochs_sovits,
                request.batch_size,
            ):
                yield f"data: {json.dumps(progress, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            logger.info(f"训练流被取消: {request.blogger_name}")
        except Exception as e:
            logger.warning(f"训练流异常: {e}")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/api/voice/synthesize")
async def synthesize(request: SynthesizeRequest):
    """语音合成"""
    # 检查模型
    model = get_trained_model_info(request.blogger_name)
    if not model.get("ready"):
        raise HTTPException(status_code=400, detail="模型未训练，请先训练模型")

    # 应用文本预处理预设
    if request.text_preset and request.text_preset in PRESETS:
        apply_preset(request.text_preset)

    result = synthesize_voice(
        text=request.text,
        blogger_name=request.blogger_name,
        speed=request.speed,
        emotion=request.emotion,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "合成失败"))

    return result


# ============================================================
# 情绪管理 API
# ============================================================

@app.get("/api/voice/emotions")
async def list_emotions():
    """获取所有可用的情绪类型"""
    return {
        "emotions": get_emotion_types(),
        "categories": EMOTION_CATEGORIES,
    }


@app.get("/api/voice/emotions/{blogger_name}/audios")
async def list_emotion_audios(blogger_name: str):
    """获取博主的所有参考音频及其情绪标签"""
    audios = get_reference_audios(blogger_name)
    stats = get_emotion_statistics(blogger_name)
    return {
        "blogger_name": blogger_name,
        "audios": audios,
        "statistics": stats,
        "emotion_types": get_emotion_types(),
    }


@app.post("/api/voice/emotions/{blogger_name}/tag")
async def tag_audio_emotion(blogger_name: str, request: TagEmotionRequest):
    """为音频设置情绪标签"""
    success = tag_emotion(blogger_name, request.filename, request.emotion)
    if not success:
        raise HTTPException(status_code=400, detail="标注失败，请检查情绪类型是否有效")
    return {
        "success": True,
        "message": f"已将 {request.filename} 标记为 {request.emotion}",
    }


@app.get("/api/voice/audio/{blogger_name}/{filename}")
async def get_audio_file(blogger_name: str, filename: str):
    """获取参考音频文件"""
    from urllib.parse import unquote

    # 确保正确解码
    blogger_name = unquote(blogger_name)
    filename = unquote(filename)

    audio_path = config.DATASETS_DIR / blogger_name / "audio" / filename
    logger.info(f"请求音频: {audio_path}, 存在: {audio_path.exists()}")

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"音频文件不存在: {audio_path}")

    return FileResponse(
        str(audio_path),
        media_type="audio/wav",
        filename=filename,
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


# ============================================================
# 文本预处理 API
# ============================================================

@app.get("/api/voice/text/presets")
async def get_text_presets():
    """获取文本预处理预设配置"""
    processor = get_text_processor()
    return {
        "presets": {
            "strict": {"name": "严格", "description": "移除所有笑声、语气词、拟声词"},
            "moderate": {"name": "适中", "description": "移除笑声，保留部分拟声词"},
            "minimal": {"name": "最小", "description": "仅移除笑声和网络用语"},
            "none": {"name": "不处理", "description": "保持原文"},
        },
        "current": {
            "remove_laughs": processor.remove_laughs,
            "simplify_fillers": processor.simplify_fillers,
            "remove_onomatopoeia": processor.remove_onomatopoeia,
            "simplify_pauses": processor.simplify_pauses,
            "remove_slang": processor.remove_slang,
        },
    }


@app.post("/api/voice/text/preview")
async def preview_text_processing(request: TextPreviewRequest):
    """预览文本预处理结果"""
    # 临时应用预设
    processor = apply_preset(request.preset)
    processed, logs = processor.process(request.text)

    return {
        "original": request.text,
        "processed": processed,
        "changes": logs,
        "preset": request.preset,
    }


@app.post("/api/voice/text/preset/{preset_name}")
async def set_text_preset(preset_name: str):
    """设置文本预处理预设"""
    if preset_name not in PRESETS:
        raise HTTPException(status_code=400, detail=f"无效的预设: {preset_name}")

    apply_preset(preset_name)
    return {"success": True, "preset": preset_name}


# ============================================================
# 表情库 API
# ============================================================

@app.get("/api/voice/expressions/types")
async def get_expression_types():
    """获取所有表情类型"""
    return {
        "types": EXPRESSION_TYPES,
        "categories": EXPRESSION_CATEGORIES,
    }


@app.get("/api/voice/expressions/{blogger_name}")
async def get_expression_library(blogger_name: str):
    """获取博主的表情库"""
    from dataclasses import asdict
    clips = load_library(blogger_name)
    stats = get_library_stats(blogger_name)

    return {
        "blogger_name": blogger_name,
        "clips": [asdict(c) for c in clips],
        "statistics": stats,
        "types": EXPRESSION_TYPES,
        "categories": EXPRESSION_CATEGORIES,
    }


@app.post("/api/voice/expressions/{blogger_name}/extract")
async def extract_expression(blogger_name: str, request: ExtractExpressionRequest):
    """从音频中提取表情片段"""
    # 构建完整路径
    audio_path = config.DATASETS_DIR / blogger_name / "audio" / request.source_audio

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    clip = extract_expression_clip(
        blogger_name=blogger_name,
        source_audio=str(audio_path),
        start_time=request.start_time,
        end_time=request.end_time,
        expression_type=request.expression_type,
        text=request.text,
    )

    if clip is None:
        raise HTTPException(status_code=500, detail="提取失败")

    from dataclasses import asdict
    return {"success": True, "clip": asdict(clip)}


@app.delete("/api/voice/expressions/{blogger_name}/{clip_id}")
async def delete_expression(blogger_name: str, clip_id: str):
    """删除表情片段"""
    success = delete_expression_clip(blogger_name, clip_id)
    if not success:
        raise HTTPException(status_code=404, detail="片段不存在")
    return {"success": True}


@app.get("/api/voice/expressions/{blogger_name}/audio/{clip_id}")
async def get_expression_audio(blogger_name: str, clip_id: str):
    """获取表情音频文件"""
    from urllib.parse import unquote

    blogger_name = unquote(blogger_name)
    clips = load_library(blogger_name)
    clip = next((c for c in clips if c.id == clip_id), None)

    if not clip:
        raise HTTPException(status_code=404, detail="片段不存在")

    from pathlib import Path
    audio_path = Path(clip.audio_path)
    if not audio_path.exists():
        raise HTTPException(status_code=404, detail="音频文件不存在")

    return FileResponse(
        str(audio_path),
        media_type="audio/wav",
        filename=f"{clip.expression_type}_{clip_id}.wav",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-cache",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )


@app.post("/api/voice/expressions/detect")
async def detect_expressions(request: TextPreviewRequest):
    """检测文本中的表情词"""
    expressions = detect_expressions_in_text(request.text)
    return {
        "text": request.text,
        "expressions": [
            {
                "type": expr_type,
                "text": matched,
                "start": start,
                "end": end,
                "type_info": EXPRESSION_TYPES.get(expr_type, {}),
            }
            for expr_type, matched, start, end in expressions
        ],
    }


@app.delete("/api/voice/dataset/{blogger_name}")
async def delete_dataset(blogger_name: str):
    """删除博主的准备数据"""
    import shutil

    dataset_dir = config.DATASETS_DIR / blogger_name

    if not dataset_dir.exists():
        raise HTTPException(status_code=404, detail="数据集不存在")

    try:
        shutil.rmtree(dataset_dir)
        return {"success": True, "message": f"已删除 {blogger_name} 的准备数据"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


@app.delete("/api/voice/model/{blogger_name}")
async def delete_model(blogger_name: str):
    """删除博主的训练模型"""
    import shutil

    model_dir = config.TRAINED_DIR / blogger_name

    if not model_dir.exists():
        raise HTTPException(status_code=404, detail="模型不存在")

    try:
        shutil.rmtree(model_dir)

        # 如果当前合成器加载的是这个博主，重置它
        synthesizer = get_synthesizer()
        if synthesizer.loaded_blogger == blogger_name:
            synthesizer.loaded_blogger = None
            synthesizer.gpt_model_path = None
            synthesizer.sovits_model_path = None
            synthesizer.ref_audio_path = None

        return {"success": True, "message": f"已删除 {blogger_name} 的训练模型"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.API_PORT)
