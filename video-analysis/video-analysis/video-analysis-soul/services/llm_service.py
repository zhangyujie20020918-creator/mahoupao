"""LLM 调用封装"""

from typing import AsyncGenerator, Dict, List, Optional

import google.generativeai as genai

from common.config import settings
from common.exceptions import LLMError, LLMTimeoutError
from common.logger import get_logger

logger = get_logger(__name__)


class LLMService:
    """LLM 服务封装"""

    def __init__(self):
        genai.configure(api_key=settings.google_api_key)
        self._models: Dict[str, genai.GenerativeModel] = {}

    def _get_model(self, model_name: str) -> genai.GenerativeModel:
        """获取或创建模型实例"""
        if model_name not in self._models:
            self._models[model_name] = genai.GenerativeModel(model_name)
        return self._models[model_name]

    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: float = 0.7,
    ) -> str:
        """生成回复（非流式）"""
        model_name = model or settings.llm.default_model

        try:
            model_instance = self._get_model(model_name)
            if system_instruction:
                model_instance = genai.GenerativeModel(
                    model_name, system_instruction=system_instruction
                )

            chat = model_instance.start_chat(history=history or [])
            response = await chat.send_message_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                ),
            )
            return response.text

        except Exception as e:
            logger.error(f"LLM generation failed: {e}", extra={"model": model_name})
            raise LLMError(f"Generation failed: {e}")

    async def generate_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_instruction: Optional[str] = None,
        history: Optional[List[Dict]] = None,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """生成回复（流式）"""
        model_name = model or settings.llm.default_model

        try:
            model_instance = self._get_model(model_name)
            if system_instruction:
                model_instance = genai.GenerativeModel(
                    model_name, system_instruction=system_instruction
                )

            chat = model_instance.start_chat(history=history or [])
            response = await chat.send_message_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=temperature,
                ),
                stream=True,
            )

            async for chunk in response:
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            logger.error(f"LLM stream failed: {e}", extra={"model": model_name})
            raise LLMError(f"Stream generation failed: {e}")

    async def analyze(
        self,
        prompt: str,
        model: Optional[str] = None,
    ) -> str:
        """使用分析模型生成（用于意图分析等轻量任务）"""
        return await self.generate(
            prompt,
            model=model or settings.llm.analysis_model,
            temperature=0.1,
        )

    async def summarize(
        self,
        prompt: str,
        model: Optional[str] = None,
    ) -> str:
        """使用总结模型生成（用于 Preview 总结等）"""
        return await self.generate(
            prompt,
            model=model or settings.llm.summary_model,
            temperature=0.3,
        )
