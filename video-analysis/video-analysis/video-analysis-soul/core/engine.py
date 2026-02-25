"""SoulEngine - 主引擎入口"""

import random
from typing import Any, AsyncGenerator, Dict, List, Optional

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
from storage.repositories.preferences_repository import PreferencesRepository

logger = get_logger(__name__)

# ── 进度提示文案池 ──────────────────────────────────
# 格式: key → (event_type, [文案列表])  或  key → [文案列表]（用于 start）
_TIPS: Dict[str, Any] = {
    "start": [
        "让我想想...",
        "嗯，收到~",
        "好的好的，马上！",
        "稍等一下下...",
        "容我思考片刻...",
        "这个问题有意思...",
        "我来看看...",
    ],
    "load_context": ("thinking", [
        "翻翻小本本...",
        "让我看看你是谁...",
        "回忆一下咱们的故事...",
        "打开记忆的大门...",
        "看看之前聊了什么...",
    ]),
    "analyze_intent": ("thinking", [
        "在琢磨你的意思...",
        "理解中...",
        "我品品...",
        "让我理解一下...",
        "嗯嗯，我在想...",
    ]),
    "search_soul": ("searching", [
        "翻箱倒柜找资料...",
        "搜索相关知识中...",
        "在知识库里挖宝...",
        "让我查查看...",
        "寻找线索中...",
        "扒拉一下素材库...",
    ]),
    "search_memory": ("searching", [
        "回忆往事中...",
        "翻翻我们的记忆...",
        "在记忆里找找...",
        "让我回想一下...",
        "搜寻记忆碎片...",
    ]),
    "load_history": ("searching", [
        "翻翻聊天记录...",
        "看看之前的对话...",
        "追溯历史对话...",
    ]),
    "generate": ("thinking", [
        "组织语言中...",
        "正在编排回复...",
        "遣词造句中...",
        "差不多想好了...",
        "酝酿中...",
        "快好了快好了...",
    ]),
}


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
        self.preferences_repo = PreferencesRepository()
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
            "preferences_repo": self.preferences_repo,
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
        soul_name: str,
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
            "soul_name": soul_name,
            "user_message": message,
            "model": model or settings.llm.default_model,
            "user_name": "",
            "is_anonymous": False,
            "is_registered": False,
            "user_preferences": {},
            "turn_count": 0,
            "intent": "chat",
            "needs_soul_knowledge": False,
            "needs_memory_recall": False,
            "memory_keywords": [],
            "soul_context": [],
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
        soul_name: str,
        message: str,
        model: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理对话请求（流式）

        使用 LangGraph astream 逐节点执行，在回复就绪后立即推送 token，
        不等待后处理节点（post_process / extract_preferences / update_memory）。

        Yields: {"event": str, "data": dict}
        """
        if self._compiled_graph is None:
            yield {"event": "error", "data": {"message": "引擎未启动"}}
            return

        yield {"event": "thinking", "data": {"message": random.choice(_TIPS["start"])}}

        # 更新用户活跃时间
        await self.user_manager.update_last_active(user_id)

        # 构建初始状态（同 chat()）
        initial_state: SoulState = {
            "user_id": user_id,
            "soul_name": soul_name,
            "user_message": message,
            "model": model or settings.llm.default_model,
            "user_name": "",
            "is_anonymous": False,
            "is_registered": False,
            "user_preferences": {},
            "turn_count": 0,
            "intent": "chat",
            "needs_soul_knowledge": False,
            "needs_memory_recall": False,
            "memory_keywords": [],
            "soul_context": [],
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

        response = None
        sources = []
        debug_info = {}
        streamed = False

        def _tip(node: str) -> tuple:
            """随机选取一条进度提示"""
            group = _TIPS.get(node)
            if not group:
                return None
            return (group[0], random.choice(group[1]))

        try:
            async for node_output in self._compiled_graph.astream(
                initial_state, stream_mode="updates"
            ):
                node_name = list(node_output.keys())[0]
                node_data = node_output[node_name]

                # 发送进度事件
                tip = _tip(node_name)
                if tip:
                    evt, msg = tip
                    yield {"event": evt, "data": {"message": msg}}

                # 捕获回复和来源
                if isinstance(node_data, dict):
                    if "response" in node_data and node_data["response"]:
                        response = node_data["response"]
                    if "sources" in node_data:
                        sources = node_data["sources"]
                    if "debug_info" in node_data:
                        debug_info.update(node_data["debug_info"])

                # connection_rewrite 完成后立即推送回复
                if node_name == "connection_rewrite" and not streamed and response:
                    streamed = True
                    chunk_size = settings.streaming.chunk_size
                    for i in range(0, len(response), chunk_size):
                        yield {
                            "event": "token",
                            "data": {"content": response[i : i + chunk_size]},
                        }

        except Exception as e:
            logger.error(f"Chat stream error: {e}", exc_info=True)
            if not streamed:
                yield {
                    "event": "error",
                    "data": {"message": "服务暂时不可用，请稍后重试"},
                }
                return

        # 兜底：如果没有经过 connection_rewrite（不应发生）
        if not streamed and response:
            chunk_size = settings.streaming.chunk_size
            for i in range(0, len(response), chunk_size):
                yield {
                    "event": "token",
                    "data": {"content": response[i : i + chunk_size]},
                }

        yield {
            "event": "done",
            "data": {"sources": sources, "debug_info": debug_info},
        }
