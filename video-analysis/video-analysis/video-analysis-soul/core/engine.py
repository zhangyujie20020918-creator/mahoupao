"""SoulEngine - 主引擎入口"""

from typing import Any, AsyncGenerator, Dict, Optional

from common.config import settings
from common.exceptions import SoulBaseError
from common.logger import get_logger
from core.graph.state import SoulState
from core.graph.workflow import build_workflow
from core.session import SessionManager
from managers.cache_manager import SessionCacheManager
from managers.memory_manager import MemoryManager
from managers.persona_manager import PersonaManager
from managers.user_manager import UserManager
from services.analysis_service import AnalysisService
from services.embedding_service import EmbeddingService
from services.generation_service import GenerationService
from services.llm_service import LLMService
from services.retrieval_service import RetrievalService

logger = get_logger(__name__)


class SoulEngine:
    """Soul 主引擎"""

    def __init__(self):
        # Services
        self.llm_service = LLMService()
        self.embedding_service = EmbeddingService()

        # Managers（PersonaManager 依赖 EmbeddingService）
        self.persona_manager = PersonaManager(self.embedding_service)
        self.user_manager = UserManager()
        self.memory_manager = MemoryManager()
        self.cache_manager = SessionCacheManager()
        self.session_manager = SessionManager(self.cache_manager)

        # Services (依赖 managers)
        self.retrieval_service = RetrievalService(self.persona_manager)
        self.analysis_service = AnalysisService(self.llm_service)
        self.generation_service = GenerationService(self.llm_service)

        # 工作流
        self._workflow = None
        self._compiled_graph = None

    async def start(self) -> None:
        """启动引擎"""
        logger.info("Starting SoulEngine...")

        # 启动缓存管理
        await self.cache_manager.start()

        # 初始化 embedding 服务（同步加载模型，首次启动较慢）
        self.embedding_service.initialize()

        # 构建 LangGraph 工作流
        deps = {
            "llm_service": self.llm_service,
            "persona_manager": self.persona_manager,
            "user_manager": self.user_manager,
            "memory_manager": self.memory_manager,
            "retrieval_service": self.retrieval_service,
            "analysis_service": self.analysis_service,
            "generation_service": self.generation_service,
        }
        self._workflow = build_workflow(deps)
        self._compiled_graph = self._workflow.compile()

        logger.info("SoulEngine started successfully")

    async def stop(self) -> None:
        """停止引擎"""
        logger.info("Stopping SoulEngine...")
        await self.cache_manager.stop()
        self.persona_manager.close()
        logger.info("SoulEngine stopped")

    async def chat(
        self,
        user_id: str,
        blogger_name: str,
        message: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        处理对话请求

        返回: {"response": str, "sources": list, "debug_info": dict}
        """
        if self._compiled_graph is None:
            raise SoulBaseError("SoulEngine not started. Call start() first.")

        # 更新用户活跃时间
        await self.user_manager.update_last_active(user_id)

        # 构建初始状态
        initial_state: SoulState = {
            "user_id": user_id,
            "blogger_name": blogger_name,
            "user_message": message,
            "model": model or settings.llm.default_model,
            "user_name": "",
            "intent": "chat",
            "needs_blogger_knowledge": False,
            "needs_memory_recall": False,
            "memory_keywords": [],
            "blogger_context": [],
            "memory_context": None,
            "detailed_history": None,
            "needs_detailed_history": False,
            "today_messages": [],
            "preview_summary": {},
            "system_prompt": "",
            "response": "",
            "sources": [],
            "debug_info": {},
        }

        # 运行工作流
        result = await self._compiled_graph.ainvoke(initial_state)

        return {
            "response": result.get("response", ""),
            "sources": result.get("sources", []),
            "debug_info": result.get("debug_info", {}),
        }

    async def chat_stream(
        self,
        user_id: str,
        blogger_name: str,
        message: str,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理对话请求（流式）

        Yields: {"event": str, "data": dict}
        """
        yield {"event": "thinking", "data": {"status": "analyzing"}}

        # 非流式运行工作流获取上下文，然后流式生成回复
        # TODO: 实现完整的流式工作流
        result = await self.chat(user_id, blogger_name, message, model)

        # 模拟流式输出
        response = result.get("response", "")
        chunk_size = settings.streaming.chunk_size
        for i in range(0, len(response), chunk_size):
            yield {
                "event": "token",
                "data": {"content": response[i : i + chunk_size]},
            }

        yield {
            "event": "done",
            "data": {
                "sources": result.get("sources", []),
                "debug_info": result.get("debug_info", {}),
            },
        }
