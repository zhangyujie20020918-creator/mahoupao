#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Video Analysis Maker - 主程序

功能：
1. 优化 ASR 转写文本（修正听写错误）
2. 构建 ChromaDB 向量数据库
3. 生成博主人格画像和系统 prompt
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

    def get_bloggers(self) -> List[Path]:
        """获取所有博主目录"""
        downloads_dir = self.settings.downloads_dir
        if not downloads_dir.exists():
            logger.error(f"Downloads directory not found: {downloads_dir}")
            return []

        bloggers = [
            d for d in downloads_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]
        return bloggers

    def process_blogger(
        self,
        blogger_dir: Path,
        skip_optimization: bool = False,
        skip_vectordb: bool = False,
        skip_persona: bool = False
    ) -> bool:
        """
        处理单个博主

        Args:
            blogger_dir: 博主目录路径
            skip_optimization: 是否跳过文本优化
            skip_vectordb: 是否跳过向量数据库构建
            skip_persona: 是否跳过人格画像生成

        Returns:
            是否成功
        """
        blogger_name = blogger_dir.name
        logger.info(f"=" * 50)
        logger.info(f"Processing blogger: {blogger_name}")
        logger.info(f"=" * 50)

        output_dir = self.settings.get_blogger_output_dir(blogger_name)
        optimized_videos: List[OptimizedVideo] = []

        # Step 1: 文本优化
        if not skip_optimization:
            logger.info("Step 1: Optimizing ASR texts...")
            self._init_optimizer()
            optimized_videos = self.text_optimizer.process_blogger(blogger_dir)

            if optimized_videos:
                self.text_optimizer.save_optimized_texts(optimized_videos, output_dir)
                logger.info(f"Optimized {len(optimized_videos)} videos")
            else:
                logger.warning("No videos optimized")
                return False
        else:
            logger.info("Step 1: Skipping text optimization, loading existing...")
            optimized_videos = self._load_optimized_videos(output_dir, blogger_name)
            if not optimized_videos:
                logger.error("No optimized videos found, cannot continue")
                return False

        # Step 2: 构建向量数据库
        if not skip_vectordb:
            logger.info("Step 2: Building vector database...")
            try:
                chroma_manager = ChromaManager(blogger_name, output_dir / "chroma_db")
                chroma_manager.add_videos(optimized_videos)
                stats = chroma_manager.get_stats()
                logger.info(f"Vector DB stats: {stats}")
            except Exception as e:
                logger.error(f"Error building vector database: {e}")
        else:
            logger.info("Step 2: Skipping vector database")

        # Step 3: 生成人格画像
        if not skip_persona:
            logger.info("Step 3: Generating blogger persona...")
            self._init_prompt_generator()
            persona = self.prompt_generator.create_blogger_persona(optimized_videos)

            if persona:
                self.prompt_generator.save_persona(persona, output_dir)
                logger.info(f"Persona generated for {blogger_name}")
                logger.info(f"Speaking style: {persona.speaking_style}")
                logger.info(f"Topics: {persona.topic_expertise}")
            else:
                logger.warning("Failed to generate persona")
        else:
            logger.info("Step 3: Skipping persona generation")

        logger.info(f"Completed processing: {blogger_name}")
        return True

    def _load_optimized_videos(self, output_dir: Path, blogger_name: str) -> List[OptimizedVideo]:
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
                    blogger_name=data["blogger_name"],
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
        blogger_name: Optional[str] = None,
        skip_optimization: bool = False,
        skip_vectordb: bool = False,
        skip_persona: bool = False
    ):
        """
        运行主处理流程

        Args:
            blogger_name: 指定博主名称，None 则处理所有博主
            skip_optimization: 是否跳过文本优化
            skip_vectordb: 是否跳过向量数据库
            skip_persona: 是否跳过人格画像
        """
        bloggers = self.get_bloggers()

        if not bloggers:
            logger.error("No bloggers found in downloads directory")
            return

        logger.info(f"Found {len(bloggers)} bloggers: {[b.name for b in bloggers]}")

        # 过滤指定博主
        if blogger_name:
            bloggers = [b for b in bloggers if b.name == blogger_name]
            if not bloggers:
                logger.error(f"Blogger not found: {blogger_name}")
                return

        # 处理每个博主
        success_count = 0
        for blogger_dir in bloggers:
            try:
                if self.process_blogger(
                    blogger_dir,
                    skip_optimization=skip_optimization,
                    skip_vectordb=skip_vectordb,
                    skip_persona=skip_persona
                ):
                    success_count += 1
            except Exception as e:
                logger.error(f"Error processing {blogger_dir.name}: {e}")
                import traceback
                traceback.print_exc()

        logger.info(f"=" * 50)
        logger.info(f"Completed: {success_count}/{len(bloggers)} bloggers processed successfully")
        logger.info(f"=" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="Video Analysis Maker - 处理博主视频内容"
    )
    parser.add_argument(
        "--blogger", "-b",
        type=str,
        default=None,
        help="指定处理的博主名称（默认处理所有博主）"
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
        "--list-bloggers",
        action="store_true",
        help="列出所有可用的博主"
    )

    args = parser.parse_args()

    maker = VideoAnalysisMaker()

    if args.list_bloggers:
        bloggers = maker.get_bloggers()
        print("\n可用的博主：")
        for b in bloggers:
            print(f"  - {b.name}")
        return

    maker.run(
        blogger_name=args.blogger,
        skip_optimization=args.skip_optimization,
        skip_vectordb=args.skip_vectordb,
        skip_persona=args.skip_persona
    )


if __name__ == "__main__":
    main()
