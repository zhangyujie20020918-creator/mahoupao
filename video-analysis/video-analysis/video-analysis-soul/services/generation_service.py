"""回复生成服务"""

from typing import AsyncGenerator, Dict, List, Optional

from common.config import settings
from common.logger import get_logger
from services.llm_service import LLMService

logger = get_logger(__name__)


class GenerationService:
    """回复生成服务"""

    def __init__(self, llm_service: LLMService):
        self._llm = llm_service

    def build_prompt(
        self,
        system_prompt: str,
        user_message: str,
        today_messages: List[Dict],
        preview_summary: Optional[str] = None,
        blogger_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        组装最终 prompt

        返回: (system_instruction, user_prompt)
        """
        # System prompt
        system_parts = [system_prompt]

        # 添加记忆上下文
        if preview_summary:
            system_parts.append(f"\n关于这位用户，你记得：\n{preview_summary}")

        system_instruction = "\n".join(system_parts)

        # User prompt 组装
        prompt_parts = []

        # 今日对话上下文
        if today_messages:
            conv_lines = []
            for msg in today_messages[-10:]:  # 最近10条
                role = "用户" if msg.get("role") == "user" else "你"
                conv_lines.append(f"{role}: {msg.get('content', '')}")
            prompt_parts.append(f"今天的对话：\n" + "\n".join(conv_lines))

        # 检索到的博主知识
        if blogger_context:
            prompt_parts.append(f"相关视频内容：\n{blogger_context}")

        # 历史记忆
        if memory_context:
            prompt_parts.append(f"相关历史记忆：\n{memory_context}")

        # 当前消息
        prompt_parts.append(f"用户: {user_message}")

        user_prompt = "\n\n".join(prompt_parts)

        return system_instruction, user_prompt

    async def generate(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        today_messages: Optional[List[Dict]] = None,
        preview_summary: Optional[str] = None,
        blogger_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> str:
        """生成回复（非流式）"""
        system_instruction, user_prompt = self.build_prompt(
            system_prompt=system_prompt,
            user_message=user_message,
            today_messages=today_messages or [],
            preview_summary=preview_summary,
            blogger_context=blogger_context,
            memory_context=memory_context,
            user_name=user_name,
        )

        return await self._llm.generate(
            prompt=user_prompt,
            model=model,
            system_instruction=system_instruction,
        )

    async def generate_stream(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str] = None,
        today_messages: Optional[List[Dict]] = None,
        preview_summary: Optional[str] = None,
        blogger_context: Optional[str] = None,
        memory_context: Optional[str] = None,
        user_name: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """生成回复（流式）"""
        system_instruction, user_prompt = self.build_prompt(
            system_prompt=system_prompt,
            user_message=user_message,
            today_messages=today_messages or [],
            preview_summary=preview_summary,
            blogger_context=blogger_context,
            memory_context=memory_context,
            user_name=user_name,
        )

        async for chunk in self._llm.generate_stream(
            prompt=user_prompt,
            model=model,
            system_instruction=system_instruction,
        ):
            yield chunk
