#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Maker - 主程序

功能：
1. 优化 ASR 转写文本（修正听写错误）
2. 构建 ChromaDB 向量数据库
3. 生成人格画像和系统 prompt
"""

import sys
import logging
import argparse
from pathlib import Path
from typing import List, Optional

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent))

from config import get_settings
from processors.text_optimizer import TextOptimizer, OptimizedVideo
from processors.prompt_generator import PromptGenerator
from storage.chroma_manager import ChromaManager

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("maker.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)


class VideoAnalysisMaker:
    """视频分析制作器主类"""

    def __init__(self):
        self.settings = get_settings()
        self.text_optimizer = None
        self.prompt_generator = None

    def _init_optimizer(self):
        """延迟初始化文本优化器"""
        if self.text_optimizer is None:
            self.text_optimizer = TextOptimizer()

    def _init_prompt_generator(self):
        """延迟初始化 prompt 生成器"""
        if self.prompt_generator is None:
            self.prompt_generator = PromptGenerator()

    def get_souls(self) -> List[Path]:
        """获取所有目录"""
        downloads_dir = self.settings.downloads_dir
        if not downloads_dir.exists():
            logger.error(f"Downloads directory not found: {downloads_dir}")
            return []

        souls = [
            d for d in downloads_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        return souls

    def process_soul(
        self,
        soul_dir: Path,
        skip_optimization: bool = False,
        skip_vectordb: bool = False,
        skip_persona: bool = False
    ) -> bool:
        """
        处理单个

        Args:
            soul_dir: 目录路径
            skip_optimization: 是否跳过文本优化
            skip_vectordb: 是否跳过向量数据库构建
            skip_persona: 是否跳过人格画像生成

        Returns:
            是否成功
        """
        soul_name = soul_dir.name
        logger.info(f"=" * 50)
        logger.info(f"Processing soul: {soul_name}")
        logger.info(f"=" * 50)

        output_dir = self.settings.get_soul_output_dir(soul_name)
        optimized_videos: List[OptimizedVideo] = []

        # Step 1: 文本优化
        if not skip_optimization:
            logger.info("Step 1: Optimizing ASR texts...")
            self._init_optimizer()
            optimized_videos = self.text_optimizer.process_soul(soul_dir)

            if optimized_videos:
                self.text_optimizer.save_optimized_texts(optimized_videos, output_dir)
                logger.info(f"Optimized {len(optimized_videos)} videos")
            else:
                logger.warning("No videos optimized")
                return False
        else:
            logger.info("Step 1: Skipping text optimization, loading existing...")
            optimized_videos = self._load_optimized_videos(output_dir, soul_name)
            if not optimized_videos:
                logger.error("No optimized videos found, cannot continue")
                return False

        # Step 2: 构建向量数据库
        if not skip_vectordb:
            logger.info("Step 2: Building vector database...")
            try:
                chroma_manager = ChromaManager(soul_name, output_dir / "chroma_db")
                chroma_manager.add_videos(optimized_videos)
                stats = chroma_manager.get_stats()
                logger.info(f"Vector DB stats: {stats}")
            except Exception as e:
                logger.error(f"Error building vector database: {e}")
        else:
            logger.info("Step 2: Skipping vector database")

        # Step 3: 生成人格画像
        if not skip_persona:
            logger.info("Step 3: Generating soul persona...")
            self._init_prompt_generator()
            persona = self.prompt_generator.create_soul_persona(optimized_videos)

            if persona:
                self.prompt_generator.save_persona(persona, output_dir)
                logger.info(f"Persona generated for {soul_name}")
                logger.info(f"Speaking style: {persona.speaking_style}")
                logger.info(f"Topics: {persona.topic_expertise}")
            else:
                logger.warning("Failed to generate persona")
        else:
            logger.info("Step 3: Skipping persona generation")

        logger.info(f"Completed processing: {soul_name}")
        return True

    def _load_optimized_videos(self, output_dir: Path, soul_name: str) -> List[OptimizedVideo]:
        """从已保存的文件加载优化后的视频"""
        import json
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

    def run(
        self,
        soul_name: Optional[str] = None,
        skip_optimization: bool = False,
        skip_vectordb: bool = False,
        skip_persona: bool = False
    ):
        """
        运行主处理流程

        Args:
            soul_name: 指定名称，None 则处理所有
            skip_optimization: 是否跳过文本优化
            skip_vectordb: 是否跳过向量数据库
            skip_persona: 是否跳过人格画像
        """
        souls = self.get_souls()

        if not souls:
            logger.error("No souls found in downloads directory")
            return

        logger.info(f"Found {len(souls)} souls: {[b.name for b in souls]}")

        # 过滤指定
        if soul_name:
            souls = [b for b in souls if b.name == soul_name]
            if not souls:
                logger.error(f"Soul not found: {soul_name}")
                return

        # 处理每个
        success_count = 0
        for soul_dir in souls:
            try:
                if self.process_soul(
                    soul_dir,
                    skip_optimization=skip_optimization,
                    skip_vectordb=skip_vectordb,
                    skip_persona=skip_persona
                ):
                    success_count += 1
            except Exception as e:
                logger.error(f"Error processing {soul_dir.name}: {e}")
                import traceback
                traceback.print_exc()

        logger.info(f"=" * 50)
        logger.info(f"Completed: {success_count}/{len(souls)} souls processed successfully")
        logger.info(f"=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Video Analysis Maker - 处理视频内容"
    )
    parser.add_argument(
        "--soul", "-b",
        type=str,
        default=None,
        help="指定处理的名称（默认处理所有）"
    )
    parser.add_argument(
        "--skip-optimization",
        action="store_true",
        help="跳过文本优化步骤（使用已有的优化结果）"
    )
    parser.add_argument(
        "--skip-vectordb",
        action="store_true",
        help="跳过向量数据库构建"
    )
    parser.add_argument(
        "--skip-persona",
        action="store_true",
        help="跳过人格画像生成"
    )
    parser.add_argument(
        "--list-souls",
        action="store_true",
        help="列出所有可用的"
    )

    args = parser.parse_args()

    maker = VideoAnalysisMaker()

    if args.list_souls:
        souls = maker.get_souls()
        print("\n可用的：")
        for b in souls:
            print(f"  - {b.name}")
        return

    maker.run(
        soul_name=args.soul,
        skip_optimization=args.skip_optimization,
        skip_vectordb=args.skip_vectordb,
        skip_persona=args.skip_persona
    )


if __name__ == "__main__":
    main()
