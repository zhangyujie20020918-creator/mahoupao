#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Maker - API 服务
"""

import json
import logging
import asyncio
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
    blogger_name: str
    skip_optimization: bool = False
    skip_vectordb: bool = False
    skip_persona: bool = False


def get_bloggers():
    """获取所有博主目录"""
    settings = get_settings()
    downloads_dir = settings.downloads_dir
    if not downloads_dir.exists():
        return []

    bloggers = []
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

            bloggers.append({
                "name": d.name,
                "video_count": len(mp4_files),
                "audio_count": len(mp3_files),
                "asr_count": len(asr_files),
                "trained": has_persona and has_vectordb,
                "has_persona": has_persona,
                "has_vectordb": has_vectordb,
                "has_optimized": has_optimized,
            })

    return bloggers


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


@app.get("/api/maker/bloggers")
async def list_bloggers():
    """列出所有博主"""
    return {"bloggers": get_bloggers()}


@app.get("/api/maker/blogger/{blogger_name}")
async def get_blogger_detail(blogger_name: str):
    """获取博主详情"""
    settings = get_settings()
    blogger_dir = settings.downloads_dir / blogger_name

    if not blogger_dir.exists():
        raise HTTPException(status_code=404, detail="博主不存在")

    output_dir = settings.output_dir / blogger_name

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
            cm = ChromaManager(blogger_name, chroma_dir)
            vectordb_stats = cm.get_stats()
        except Exception as e:
            logger.error(f"Error getting vectordb stats: {e}")

    return {
        "name": blogger_name,
        "persona": persona,
        "system_prompt": system_prompt,
        "vectordb_stats": vectordb_stats,
    }


@app.post("/api/maker/train")
async def train_blogger(request: TrainRequest):
    """训练博主 (流式响应)"""

    async def generate() -> AsyncGenerator[str, None]:
        settings = get_settings()
        blogger_dir = settings.downloads_dir / request.blogger_name

        if not blogger_dir.exists():
            yield f"data: {json.dumps({'type': 'error', 'message': '博主目录不存在'})}\n\n"
            return

        output_dir = settings.get_blogger_output_dir(request.blogger_name)

        try:
            # Step 1: 文本优化
            if not request.skip_optimization:
                yield f"data: {json.dumps({'type': 'step', 'step': 1, 'message': '正在优化 ASR 文本...'})}\n\n"
                await asyncio.sleep(0.1)

                optimizer = TextOptimizer()

                # 获取所有 ASR 文件
                json_files = [f for f in blogger_dir.glob("*.json") if not f.name.startswith("_")]
                total = len(json_files)

                if total == 0:
                    yield f"data: {json.dumps({'type': 'error', 'message': '没有找到 ASR 文件，请先进行数据清洗'})}\n\n"
                    return

                optimized_videos = []
                for i, json_path in enumerate(json_files):
                    yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'current': i+1, 'total': total, 'file': json_path.stem})}\n\n"
                    await asyncio.sleep(0.1)

                    result = optimizer.process_video_file(json_path, request.blogger_name)
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
                optimized_videos = load_optimized_videos(output_dir, request.blogger_name)
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
                    chroma_manager = ChromaManager(request.blogger_name, output_dir / "chroma_db")
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
                    persona = generator.create_blogger_persona(optimized_videos)

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


def load_optimized_videos(output_dir: Path, blogger_name: str):
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
                blogger_name=data["blogger_name"],
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
