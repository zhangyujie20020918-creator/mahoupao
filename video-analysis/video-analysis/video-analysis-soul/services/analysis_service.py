"""意图/情绪分析服务"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from common.config import settings, BASE_DIR
from common.logger import get_logger
from services.llm_service import LLMService

logger = get_logger(__name__)


class AnalysisService:
    """分析服务 - 意图分析、情绪检测、信息提取"""

    def __init__(self, llm_service: LLMService):
        self._llm = llm_service
        self._intent_prompt = self._load_prompt("intent_analysis.txt")
        self._emotion_prompt = self._load_prompt("emotion_detection.txt")
        self._extraction_prompt = self._load_prompt("info_extraction.txt")

    def _load_prompt(self, filename: str) -> str:
        """加载 prompt 模板"""
        path = BASE_DIR / "config" / "prompts" / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    @staticmethod
    def _parse_llm_json(text: str) -> Any:
        """解析 LLM 返回的 JSON（自动处理 markdown 代码块包裹）"""
        text = text.strip()
        # 去掉 ```json ... ``` 或 ``` ... ``` 包裹
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        return json.loads(text)

    async def analyze_intent(
        self,
        user_message: str,
        today_messages: List[Dict],
        preview_summary: Optional[Dict] = None,
    ) -> Dict:
        """
        分析用户意图

        返回:
        {
            "intent": "greeting" | "question" | "recall" | "chat" | "farewell",
            "needs_blogger_knowledge": bool,
            "needs_memory_recall": bool,
            "memory_keywords": list[str],
            "confidence": float
        }
        """
        prompt = self._intent_prompt or self._default_intent_prompt()

        context = f"""用户消息: {user_message}

今日对话记录数: {len(today_messages)}
最近几条对话: {json.dumps(today_messages[-3:], ensure_ascii=False) if today_messages else '无'}
"""
        if preview_summary:
            context += f"\n用户历史记忆摘要: {json.dumps(preview_summary, ensure_ascii=False)}"

        full_prompt = f"{prompt}\n\n{context}\n\n请以 JSON 格式返回分析结果。"

        try:
            result_text = await self._llm.analyze(full_prompt)
            return self._parse_llm_json(result_text)
        except Exception as e:
            logger.warning(f"Intent analysis failed, using defaults: {e}")
            return self._default_intent_result(user_message)

    async def detect_emotion(self, user_message: str) -> Dict:
        """检测用户情绪"""
        # 先用规则检测
        rule_result = self._rule_based_emotion(user_message)
        if rule_result:
            return rule_result

        # 规则无法判断时使用 LLM
        if self._emotion_prompt:
            try:
                result_text = await self._llm.analyze(
                    f"{self._emotion_prompt}\n\n用户消息: {user_message}"
                )
                return self._parse_llm_json(result_text)
            except Exception:
                pass

        return {"emotion": "neutral", "confidence": 0.5}

    async def extract_info(self, messages: List[Dict]) -> Dict:
        """从对话中提取关键信息"""
        if not self._extraction_prompt:
            return {}

        try:
            conv_text = "\n".join(
                f"{m.get('role', 'user')}: {m.get('content', '')}" for m in messages
            )
            result_text = await self._llm.analyze(
                f"{self._extraction_prompt}\n\n对话内容:\n{conv_text}"
            )
            return self._parse_llm_json(result_text)
        except Exception as e:
            logger.warning(f"Info extraction failed: {e}")
            return {}

    def _rule_based_emotion(self, text: str) -> Optional[Dict]:
        """基于规则的情绪检测"""
        triggers = settings.analysis.emotion.general_triggers
        emotion_labels = ["positive", "negative", "anxious", "angry"]

        for i, trigger_group in enumerate(triggers):
            for trigger in trigger_group:
                if trigger in text:
                    return {
                        "emotion": emotion_labels[i] if i < len(emotion_labels) else "neutral",
                        "trigger": trigger,
                        "confidence": 0.8,
                    }
        return None

    def _default_intent_result(self, message: str) -> Dict:
        """默认意图分析结果"""
        # 简单规则判断
        greeting_words = ["你好", "hi", "hello", "嗨", "在吗"]
        farewell_words = ["再见", "拜拜", "bye", "下次见"]
        recall_words = ["之前", "上次", "记得", "昨天", "以前"]

        msg_lower = message.lower()

        if any(w in msg_lower for w in greeting_words):
            intent = "greeting"
        elif any(w in msg_lower for w in farewell_words):
            intent = "farewell"
        elif any(w in msg_lower for w in recall_words):
            intent = "recall"
        elif "?" in message or "？" in message:
            intent = "question"
        else:
            intent = "chat"

        return {
            "intent": intent,
            "needs_blogger_knowledge": intent == "question",
            "needs_memory_recall": intent == "recall",
            "memory_keywords": [],
            "confidence": 0.6,
        }

    def _default_intent_prompt(self) -> str:
        return """你是一个意图分析助手。分析用户消息的意图。

可能的意图类型：
- greeting: 打招呼
- question: 专业问题（需要博主知识库）
- recall: 提及过去的事情（需要记忆检索）
- chat: 日常闲聊
- farewell: 告别

请返回 JSON 格式：
{
    "intent": "意图类型",
    "needs_blogger_knowledge": true/false,
    "needs_memory_recall": true/false,
    "memory_keywords": ["关键词1", "关键词2"],
    "confidence": 0.0-1.0
}"""
