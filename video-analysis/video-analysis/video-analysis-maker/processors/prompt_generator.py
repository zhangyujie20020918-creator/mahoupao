import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import google.generativeai as genai

from config import get_settings
from processors.text_optimizer import OptimizedVideo

logger = logging.getLogger(__name__)


@dataclass
class SoulPersona:
    """人格画像"""
    soul_name: str
    speaking_style: str          # 说话风格
    common_phrases: List[str]    # 常用语句/口头禅
    topic_expertise: List[str]   # 擅长话题
    personality_traits: List[str] # 性格特点
    tone: str                    # 语气
    target_audience: str         # 目标受众
    content_patterns: str        # 内容模式
    system_prompt: str           # 生成的系统 prompt

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PromptGenerator:
    """分析风格并生成模拟 prompt"""

    ANALYSIS_PROMPT = """你是一个专业的内容分析专家。请分析以下的视频文本内容，提取其说话风格和人物特征。

名称：{soul_name}

以下是该的多个视频文本内容：
---
{video_texts}
---

请分析并以 JSON 格式输出以下信息：
{{
    "speaking_style": "说话风格描述（如：直接犀利、幽默风趣、专业严谨等）",
    "common_phrases": ["常用的口头禅或标志性句子", "开场白", "结束语"],
    "topic_expertise": ["擅长的话题领域1", "话题2", "话题3"],
    "personality_traits": ["性格特点1", "特点2", "特点3"],
    "tone": "整体语气（如：轻松幽默、严肃认真、激情澎湃等）",
    "target_audience": "目标受众群体描述",
    "content_patterns": "内容组织模式（如：先抛出问题再解答、用数据说话、讲故事等）"
}}

只返回 JSON，不要其他内容："""

    PERSONA_PROMPT_TEMPLATE = """你是一个专业的 AI 角色设计师。基于以下的人物分析，请生成一个用于让 AI 模拟该进行对话的系统 prompt。

名称：{soul_name}

人物分析：
- 说话风格：{speaking_style}
- 常用语句：{common_phrases}
- 擅长话题：{topic_expertise}
- 性格特点：{personality_traits}
- 语气：{tone}
- 目标受众：{target_audience}
- 内容模式：{content_patterns}

示例对话内容：
{sample_texts}

请生成一个详细的系统 prompt，要求：
1. 让 AI 能准确模拟该的说话风格和语气
2. 包含该的知识领域和专业背景
3. 包含该的常用表达方式和口头禅
4. 指导 AI 如何组织回答内容
5. prompt 应该是第二人称，直接告诉 AI "你是..."

直接输出系统 prompt 内容，不需要额外说明："""

    def __init__(self):
        self.settings = get_settings()
        genai.configure(api_key=self.settings.gemini_api_key)
        self.model = genai.GenerativeModel(self.settings.gemini_model)
        logger.info(f"PromptGenerator initialized with model: {self.settings.gemini_model}")

    def analyze_soul(self, videos: List[OptimizedVideo]) -> Optional[Dict[str, Any]]:
        """
        分析的说话风格和特征

        Args:
            videos: 的视频列表

        Returns:
            分析结果字典
        """
        if not videos:
            logger.warning("No videos provided for analysis")
            return None

        soul_name = videos[0].soul_name

        # 组合所有视频文本
        video_texts = "\n\n".join([
            f"【{v.video_title}】\n{v.optimized_full_text}"
            for v in videos[:10]  # 最多取10个视频避免超过token限制
        ])

        try:
            prompt = self.ANALYSIS_PROMPT.format(
                soul_name=soul_name,
                video_texts=video_texts
            )

            response = self.model.generate_content(prompt)
            result_text = response.text.strip()

            # 清理可能的 markdown 代码块
            if result_text.startswith("```"):
                lines = result_text.split("\n")
                result_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

            analysis = json.loads(result_text)
            logger.info(f"Successfully analyzed soul: {soul_name}")
            return analysis

        except Exception as e:
            logger.error(f"Error analyzing soul {soul_name}: {e}")
            return None

    def generate_persona_prompt(
        self,
        soul_name: str,
        analysis: Dict[str, Any],
        sample_videos: List[OptimizedVideo]
    ) -> str:
        """
        生成模拟的系统 prompt

        Args:
            soul_name: 名称
            analysis: 分析结果
            sample_videos: 示例视频

        Returns:
            系统 prompt
        """
        # 准备示例文本
        sample_texts = "\n\n".join([
            f"【{v.video_title}】\n{v.optimized_full_text[:500]}..."
            for v in sample_videos[:3]
        ])

        try:
            prompt = self.PERSONA_PROMPT_TEMPLATE.format(
                soul_name=soul_name,
                speaking_style=analysis.get("speaking_style", "未知"),
                common_phrases=", ".join(analysis.get("common_phrases", [])),
                topic_expertise=", ".join(analysis.get("topic_expertise", [])),
                personality_traits=", ".join(analysis.get("personality_traits", [])),
                tone=analysis.get("tone", "未知"),
                target_audience=analysis.get("target_audience", "未知"),
                content_patterns=analysis.get("content_patterns", "未知"),
                sample_texts=sample_texts
            )

            response = self.model.generate_content(prompt)
            system_prompt = response.text.strip()
            logger.info(f"Successfully generated persona prompt for: {soul_name}")
            return system_prompt

        except Exception as e:
            logger.error(f"Error generating persona prompt: {e}")
            return self._generate_fallback_prompt(soul_name, analysis)

    def _generate_fallback_prompt(self, soul_name: str, analysis: Dict[str, Any]) -> str:
        """生成降级版本的系统 prompt"""
        return f"""你是{soul_name}，一位专注于{", ".join(analysis.get("topic_expertise", ["财经"]))}领域的内容创作者。

你的说话风格是{analysis.get("speaking_style", "专业且亲切")}，语气{analysis.get("tone", "轻松但不失专业")}。

你常说的话包括：{", ".join(analysis.get("common_phrases", []))}

在回答问题时，请：
1. 保持你一贯的{analysis.get("speaking_style", "专业")}风格
2. 使用你常用的表达方式和口头禅
3. 围绕你擅长的{", ".join(analysis.get("topic_expertise", ["财经"]))}领域展开
4. 以你的目标受众（{analysis.get("target_audience", "普通用户")}）能理解的方式表达
5. 按照你惯常的内容模式（{analysis.get("content_patterns", "清晰有条理")}）组织回答
"""

    def create_soul_persona(self, videos: List[OptimizedVideo]) -> Optional[SoulPersona]:
        """
        创建完整的人格画像

        Args:
            videos: 的视频列表

        Returns:
            SoulPersona 对象
        """
        if not videos:
            return None

        soul_name = videos[0].soul_name

        # 分析
        analysis = self.analyze_soul(videos)
        if not analysis:
            return None

        # 生成系统 prompt
        system_prompt = self.generate_persona_prompt(soul_name, analysis, videos)

        # 创建人格画像
        persona = SoulPersona(
            soul_name=soul_name,
            speaking_style=analysis.get("speaking_style", ""),
            common_phrases=analysis.get("common_phrases", []),
            topic_expertise=analysis.get("topic_expertise", []),
            personality_traits=analysis.get("personality_traits", []),
            tone=analysis.get("tone", ""),
            target_audience=analysis.get("target_audience", ""),
            content_patterns=analysis.get("content_patterns", ""),
            system_prompt=system_prompt
        )

        return persona

    def save_persona(self, persona: SoulPersona, output_dir: Path):
        """保存人格画像"""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 保存完整的人格画像（JSON）
        persona_path = output_dir / "persona.json"
        with open(persona_path, "w", encoding="utf-8") as f:
            json.dump(persona.to_dict(), f, ensure_ascii=False, indent=2)

        # 单独保存系统 prompt（方便使用）
        prompt_path = output_dir / "system_prompt.txt"
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write(persona.system_prompt)

        logger.info(f"Saved persona for {persona.soul_name} to {output_dir}")
