import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import google.generativeai as genai
from tqdm import tqdm

from config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class OptimizedSegment:
    """优化后的文本段落"""
    original_text: str
    optimized_text: str
    start: float
    end: float
    segment_index: int


@dataclass
class OptimizedVideo:
    """优化后的视频文本"""
    video_title: str
    soul_name: str
    original_full_text: str
    optimized_full_text: str
    segments: List[OptimizedSegment] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "video_title": self.video_title,
            "soul_name": self.soul_name,
            "original_full_text": self.original_full_text,
            "optimized_full_text": self.optimized_full_text,
            "segments": [asdict(seg) for seg in self.segments]
        }


class TextOptimizer:
    """使用 Gemini 优化 ASR 转写文本"""

    OPTIMIZATION_PROMPT = """你是一个专业的中文文本校对专家。请帮我优化以下由语音识别(ASR)生成的文本。

任务要求：
1. 修正明显的听写错误（如同音字错误："马农"→"码农"，"只要"→"只有"等）
2. 调整标点符号，使句子更通顺
3. 保持原有的口语化风格和说话习惯，不要改成书面语
4. 不要添加或删除内容，只做修正
5. 保持原有的段落结构

原始文本：
{text}

请直接输出优化后的文本，不需要解释："""

    BATCH_OPTIMIZATION_PROMPT = """你是一个专业的中文文本校对专家。请帮我优化以下由语音识别(ASR)生成的多段文本。

任务要求：
1. 修正明显的听写错误（如同音字错误："马农"→"码农"，"只要"→"只有"等）
2. 调整标点符号，使句子更通顺
3. 保持原有的口语化风格和说话习惯，不要改成书面语
4. 不要添加或删除内容，只做修正
5. 每段文本单独处理，保持段落数量一致

原始文本段落（JSON格式）：
{segments_json}

请以JSON数组格式返回优化后的文本，每个元素对应一个段落，例如：
["优化后的第一段", "优化后的第二段", ...]

只返回JSON数组，不要其他内容："""

    def __init__(self):
        self.settings = get_settings()
        genai.configure(api_key=self.settings.gemini_api_key)
        self.model = genai.GenerativeModel(self.settings.gemini_model)
        logger.info(f"TextOptimizer initialized with model: {self.settings.gemini_model}")

    def optimize_text(self, text: str) -> str:
        """优化单段文本"""
        try:
            prompt = self.OPTIMIZATION_PROMPT.format(text=text)
            response = self.model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            logger.error(f"Error optimizing text: {e}")
            return text  # 失败时返回原文

    def optimize_segments_batch(self, segments: List[Dict[str, Any]]) -> List[str]:
        """批量优化多个段落"""
        if not segments:
            return []

        texts = [seg.get("text", "") for seg in segments]
        segments_json = json.dumps(texts, ensure_ascii=False, indent=2)

        try:
            prompt = self.BATCH_OPTIMIZATION_PROMPT.format(segments_json=segments_json)
            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            # 清理可能的 markdown 代码块标记
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                result_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            optimized_texts = json.loads(result_text)

            if len(optimized_texts) != len(segments):
                logger.warning(f"Segment count mismatch: {len(optimized_texts)} vs {len(segments)}")
                # 尝试匹配或返回原文
                while len(optimized_texts) < len(segments):
                    optimized_texts.append(texts[len(optimized_texts)])

            return optimized_texts

        except Exception as e:
            logger.error(f"Error batch optimizing segments: {e}")
            return texts  # 失败时返回原文列表

    def process_video_file(self, json_path: Path, soul_name: str) -> Optional[OptimizedVideo]:
        """处理单个视频的 JSON 文件"""
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            video_title = json_path.stem
            original_full_text = data.get("text", "")
            segments_data = data.get("segments", [])

            if not segments_data:
                # 如果没有分段，直接优化整体文本
                optimized_full_text = self.optimize_text(original_full_text)
                return OptimizedVideo(
                    video_title=video_title,
                    soul_name=soul_name,
                    original_full_text=original_full_text,
                    optimized_full_text=optimized_full_text,
                    segments=[]
                )

            # 批量优化分段
            optimized_texts = self.optimize_segments_batch(segments_data)

            # 构建优化后的分段
            optimized_segments = []
            for i, (seg, opt_text) in enumerate(zip(segments_data, optimized_texts)):
                optimized_segments.append(OptimizedSegment(
                    original_text=seg.get("text", ""),
                    optimized_text=opt_text,
                    start=seg.get("start", 0.0),
                    end=seg.get("end", 0.0),
                    segment_index=i
                ))

            # 拼接完整的优化文本
            optimized_full_text = "".join(optimized_texts)

            return OptimizedVideo(
                video_title=video_title,
                soul_name=soul_name,
                original_full_text=original_full_text,
                optimized_full_text=optimized_full_text,
                segments=optimized_segments
            )

        except Exception as e:
            logger.error(f"Error processing video file {json_path}: {e}")
            return None

    def process_soul(self, soul_dir: Path) -> List[OptimizedVideo]:
        """处理一个的所有视频"""
        soul_name = soul_dir.name
        logger.info(f"Processing soul: {soul_name}")

        # 获取所有 ASR JSON 文件（排除 _metadata.json）
        json_files = [
            f for f in soul_dir.glob("*.json")
            if not f.name.startswith("_")
        ]

        optimized_videos = []
        for json_path in tqdm(json_files, desc=f"Optimizing {soul_name}"):
            result = self.process_video_file(json_path, soul_name)
            if result:
                optimized_videos.append(result)

        logger.info(f"Processed {len(optimized_videos)} videos for {soul_name}")
        return optimized_videos

    def save_optimized_texts(self, videos: List[OptimizedVideo], output_dir: Path):
        """保存优化后的文本"""
        optimized_dir = output_dir / "optimized_texts"
        optimized_dir.mkdir(parents=True, exist_ok=True)

        for video in videos:
            # 保存为 JSON（包含分段信息）
            json_path = optimized_dir / f"{video.video_title}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(video.to_dict(), f, ensure_ascii=False, indent=2)

            # 保存纯文本版本
            txt_path = optimized_dir / f"{video.video_title}.txt"
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(video.optimized_full_text)

        logger.info(f"Saved {len(videos)} optimized texts to {optimized_dir}")
