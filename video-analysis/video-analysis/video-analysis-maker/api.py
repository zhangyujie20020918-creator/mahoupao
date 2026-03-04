#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Maker - API 服务
"""

import json
import logging
import asyncio
import shutil
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config import get_settings
from processors.text_optimizer import TextOptimizer, OptimizedVideo
from processors.prompt_generator import PromptGenerator
from storage.chroma_manager import ChromaManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Video Analysis Maker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TrainRequest(BaseModel):
    soul_name: str
    skip_optimization: bool = False
    skip_vectordb: bool = False
    skip_persona: bool = False


def get_souls():
    """获取所有目录"""
    settings = get_settings()
    downloads_dir = settings.downloads_dir
    if not downloads_dir.exists():
        return []

    souls = []
    for d in downloads_dir.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            # 统计文件
            json_files = list(d.glob("*.json"))
            asr_files = [f for f in json_files if not f.name.startswith("_")]
            mp4_files = list(d.glob("*.mp4"))
            mp3_files = list(d.glob("*.mp3"))

            # 检查是否已训练
            output_dir = settings.output_dir / d.name
            has_persona = (output_dir / "persona.json").exists()
            has_vectordb = (output_dir / "chroma_db").exists()
            has_optimized = (output_dir / "optimized_texts").exists()

            souls.append({
                "name": d.name,
                "video_count": len(mp4_files),
                "audio_count": len(mp3_files),
                "asr_count": len(asr_files),
                "trained": has_persona and has_vectordb,
                "has_persona": has_persona,
                "has_vectordb": has_vectordb,
                "has_optimized": has_optimized,
            })

    return souls


@app.get("/api/maker/status")
async def get_status():
    """获取服务状态"""
    settings = get_settings()

    # 检查 Gemini API
    gemini_configured = bool(settings.gemini_api_key)

    # 检查 GPU
    try:
        import torch
        gpu_available = torch.cuda.is_available()
        gpu_name = torch.cuda.get_device_name(0) if gpu_available else None
    except:
        gpu_available = False
        gpu_name = None

    return {
        "online": True,
        "gemini_configured": gemini_configured,
        "gemini_model": settings.gemini_model,
        "embedding_model": settings.embedding_model,
        "gpu": {
            "available": gpu_available,
            "name": gpu_name,
        },
        "downloads_dir": str(settings.downloads_dir),
        "output_dir": str(settings.output_dir),
    }


@app.get("/api/maker/souls")
async def list_souls():
    """列出所有"""
    return {"souls": get_souls()}


@app.get("/api/maker/soul/{soul_name}")
async def get_soul_detail(soul_name: str):
    """获取详情"""
    settings = get_settings()
    soul_dir = settings.downloads_dir / soul_name

    if not soul_dir.exists():
        raise HTTPException(status_code=404, detail="不存在")

    output_dir = settings.output_dir / soul_name

    # 读取人格画像
    persona = None
    persona_file = output_dir / "persona.json"
    if persona_file.exists():
        with open(persona_file, "r", encoding="utf-8") as f:
            persona = json.load(f)

    # 读取系统 prompt
    system_prompt = None
    prompt_file = output_dir / "system_prompt.txt"
    if prompt_file.exists():
        with open(prompt_file, "r", encoding="utf-8") as f:
            system_prompt = f.read()

    # 向量数据库统计
    vectordb_stats = None
    chroma_dir = output_dir / "chroma_db"
    if chroma_dir.exists():
        try:
            cm = ChromaManager(soul_name, chroma_dir)
            vectordb_stats = cm.get_stats()
        except Exception as e:
            logger.error(f"Error getting vectordb stats: {e}")

    return {
        "name": soul_name,
        "persona": persona,
        "system_prompt": system_prompt,
        "vectordb_stats": vectordb_stats,
    }


@app.post("/api/maker/train")
async def train_soul(request: TrainRequest):
    """训练 (流式响应)"""

    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        soul_dir = settings.downloads_dir / request.soul_name

        if not soul_dir.exists():
            yield f"data: {json.dumps({'type': 'error', 'message': '目录不存在'})}\n\n"
            return

        output_dir = settings.get_soul_output_dir(request.soul_name)

        try:
            # Step 1: 文本优化
            if not request.skip_optimization:
                yield f"data: {json.dumps({'type': 'step', 'step': 1, 'message': '正在优化 ASR 文本...'})}\n\n"
                await asyncio.sleep(0.1)

                optimizer = TextOptimizer()

                # 获取所有 ASR 文件
                json_files = [f for f in soul_dir.glob("*.json") if not f.name.startswith("_")]
                total = len(json_files)

                if total == 0:
                    yield f"data: {json.dumps({'type': 'error', 'message': '没有找到 ASR 文件，请先进行数据清洗'})}\n\n"
                    return

                optimized_videos = []
                for i, json_path in enumerate(json_files):
                    yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'current': i+1, 'total': total, 'file': json_path.stem})}\n\n"
                    await asyncio.sleep(0.1)

                    result = optimizer.process_video_file(json_path, request.soul_name)
                    if result:
                        optimized_videos.append(result)

                if optimized_videos:
                    optimizer.save_optimized_texts(optimized_videos, output_dir)
                    yield f"data: {json.dumps({'type': 'step_done', 'step': 1, 'message': f'优化完成，处理了 {len(optimized_videos)} 个视频'})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'error', 'message': '文本优化失败'})}\n\n"
                    return
            else:
                yield f"data: {json.dumps({'type': 'step', 'step': 1, 'message': '跳过文本优化，加载已有结果...'})}\n\n"
                optimized_videos = load_optimized_videos(output_dir, request.soul_name)
                if not optimized_videos:
                    yield f"data: {json.dumps({'type': 'error', 'message': '没有找到已优化的文本'})}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'step_done', 'step': 1, 'message': f'已加载 {len(optimized_videos)} 个优化文本'})}\n\n"

            await asyncio.sleep(0.1)

            # Step 2: 构建向量数据库
            if not request.skip_vectordb:
                yield f"data: {json.dumps({'type': 'step', 'step': 2, 'message': '正在构建向量数据库...'})}\n\n"
                await asyncio.sleep(0.1)

                try:
                    chroma_manager = ChromaManager(request.soul_name, output_dir / "chroma_db")
                    chroma_manager.add_videos(optimized_videos)
                    stats = chroma_manager.get_stats()
                    doc_count = stats['document_count']
                    msg = f'向量数据库构建完成，共 {doc_count} 条记录'
                    yield f"data: {json.dumps({'type': 'step_done', 'step': 2, 'message': msg})}\n\n"
                except Exception as e:
                    err_msg = f'向量数据库构建失败: {str(e)}'
                    yield f"data: {json.dumps({'type': 'warning', 'step': 2, 'message': err_msg})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'step', 'step': 2, 'message': '跳过向量数据库构建'})}\n\n"

            await asyncio.sleep(0.1)

            # Step 3: 生成人格画像
            if not request.skip_persona:
                yield f"data: {json.dumps({'type': 'step', 'step': 3, 'message': '正在生成人格画像...'})}\n\n"
                await asyncio.sleep(0.1)

                try:
                    generator = PromptGenerator()
                    persona = generator.create_soul_persona(optimized_videos)

                    if persona:
                        generator.save_persona(persona, output_dir)
                        yield f"data: {json.dumps({'type': 'step_done', 'step': 3, 'message': '人格画像生成完成'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'type': 'warning', 'step': 3, 'message': '人格画像生成失败'})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'type': 'warning', 'step': 3, 'message': f'人格画像生成失败: {str(e)}'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'step', 'step': 3, 'message': '跳过人格画像生成'})}\n\n"

            # 完成
            yield f"data: {json.dumps({'type': 'done', 'message': '训练完成！'})}\n\n"

        except Exception as e:
            logger.exception("Training error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


@app.get("/api/maker/soul/{soul_name}/archive-status")
async def get_archive_status(soul_name: str):
    """检查归档条件"""
    settings = get_settings()
    downloads_dir = settings.downloads_dir / soul_name

    if not downloads_dir.exists():
        raise HTTPException(status_code=404, detail="不存在")

    # 检查 maker 已训练
    output_dir = settings.output_dir / soul_name
    has_persona = (output_dir / "persona.json").exists()
    has_vectordb = (output_dir / "chroma_db").exists()
    maker_trained = has_persona and has_vectordb

    # 检查 voice-cloning 已切片
    voice_datasets_dir = settings.base_dir.parent / "video-analysis-voice-cloning" / "datasets" / soul_name / "audio"
    voice_cloned = voice_datasets_dir.exists() and any(voice_datasets_dir.glob("*.wav"))

    # 统计文件
    mp4_count = len(list(downloads_dir.glob("*.mp4")))
    mp3_count = len(list(downloads_dir.glob("*.mp3")))
    txt_count = len(list(downloads_dir.glob("*.txt")))
    srt_count = len(list(downloads_dir.glob("*.srt")))
    json_count = len(list(downloads_dir.glob("*.json")))

    total_size = sum(f.stat().st_size for f in downloads_dir.rglob("*") if f.is_file())
    total_size_mb = round(total_size / (1024 * 1024), 1)

    return {
        "can_archive": maker_trained and voice_cloned,
        "maker_trained": maker_trained,
        "voice_cloned": voice_cloned,
        "file_stats": {
            "mp4_count": mp4_count,
            "mp3_count": mp3_count,
            "txt_count": txt_count,
            "srt_count": srt_count,
            "json_count": json_count,
            "total_size_mb": total_size_mb,
        }
    }


@app.post("/api/maker/soul/{soul_name}/archive")
async def archive_soul(soul_name: str):
    """执行归档：将 downloads/soul_name 移动到 archive/soul_name"""
    settings = get_settings()
    downloads_dir = settings.downloads_dir / soul_name

    if not downloads_dir.exists():
        raise HTTPException(status_code=404, detail="不存在")

    archive_base = settings.downloads_dir.parent / "archive"
    archive_dir = archive_base / soul_name

    if archive_dir.exists():
        raise HTTPException(status_code=409, detail=f"归档目录已存在: archive/{soul_name}")

    # 计算大小
    total_size = sum(f.stat().st_size for f in downloads_dir.rglob("*") if f.is_file())
    total_size_mb = round(total_size / (1024 * 1024), 1)

    # 执行移动
    archive_base.mkdir(parents=True, exist_ok=True)
    shutil.move(str(downloads_dir), str(archive_dir))
    logger.info(f"Archived {soul_name}: {downloads_dir} -> {archive_dir}")

    return {
        "success": True,
        "archived_to": f"archive/{soul_name}",
        "size_mb": total_size_mb,
    }


@app.get("/api/maker/archived")
async def list_archived():
    """列出已归档的 soul"""
    settings = get_settings()
    archive_base = settings.downloads_dir.parent / "archive"

    if not archive_base.exists():
        return {"archived": []}

    archived = []
    for d in archive_base.iterdir():
        if d.is_dir() and not d.name.startswith("."):
            files = [f for f in d.rglob("*") if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)
            archived.append({
                "name": d.name,
                "file_count": len(files),
                "size_mb": round(total_size / (1024 * 1024), 1),
            })

    return {"archived": archived}


def load_optimized_videos(output_dir: Path, soul_name: str):
    """从已保存的文件加载优化后的视频"""
    from processors.text_optimizer import OptimizedVideo, OptimizedSegment

    optimized_dir = output_dir / "optimized_texts"
    if not optimized_dir.exists():
        return []

    videos = []
    for json_file in optimized_dir.glob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            segments = [
                OptimizedSegment(
                    original_text=seg["original_text"],
                    optimized_text=seg["optimized_text"],
                    start=seg["start"],
                    end=seg["end"],
                    segment_index=seg["segment_index"]
                )
                for seg in data.get("segments", [])
            ]

            video = OptimizedVideo(
                video_title=data["video_title"],
                soul_name=data["soul_name"],
                original_full_text=data["original_full_text"],
                optimized_full_text=data["optimized_full_text"],
                segments=segments
            )
            videos.append(video)
        except Exception as e:
            logger.error(f"Error loading {json_file}: {e}")

    return videos


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
