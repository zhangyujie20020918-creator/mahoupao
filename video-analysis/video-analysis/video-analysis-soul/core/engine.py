"""SoulEngine - 主引擎入口"""

import asyncio
import random
from typing import Any, AsyncGenerator, Dict, List, Optional

from common.config import settings
from common.exceptions import SoulBaseError
from common.logger import get_logger
from common.utils.text import find_sentence_boundary
from core.graph.nodes.connection_rewrite import (
    _get_missing_dimensions,
    _pick_target_dimension,
)
from core.graph.nodes.extract_preferences import extract_preferences
from core.graph.nodes.post_process import post_process
from core.graph.nodes.update_memory import update_memory
from core.graph.state import SoulState
from core.graph.workflow import build_context_workflow, build_workflow
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
from services.tts_service import TTSService
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


def _tip(node: str):
    """随机选取一条进度提示"""
    group = _TIPS.get(node)
    if not group:
        return None
    return (group[0], random.choice(group[1]))


def _inject_connection_instructions(system_prompt: str, state: dict) -> str:
    """将连接建立指导注入 system prompt（代替 connection_rewrite 节点）"""
    user_preferences = state.get("user_preferences", {})
    turn_count = state.get("turn_count", 0)

    missing_dims = _get_missing_dimensions(user_preferences)
    target_dim = _pick_target_dimension(missing_dims)

    nudge_line = ""
    if turn_count >= settings.connection_agent.nudge_threshold:
        nudge_line = "- 可以温柔提一句注册好处，例如「对了，如果你注册一下，下次来我就能记住你啦~」"

    connection_section = f"""

## 连接建立指导 (对匿名用户)

这位用户还没有注册。在回复中可以适度融入关系建立元素：
- 还需了解的维度：{"、".join(missing_dims) if missing_dims else "无"}
- 本轮建议探索：{target_dim}
- 已聊轮数：{turn_count}
- 规则：每次最多追加一个简短探索性元素，不要每轮都追加，要与话题自然衔接
- 不要暴露你是"连接助手"，保持你的人设
- 如果用户表现出抵触或不耐烦，不要追问
- 不要使用重复的收尾套话
{nudge_line}"""

    return system_prompt + connection_section


def _prepare_generation_context(state: dict, retrieval_service) -> dict:
    """
    从 context state 中提取并格式化生成所需的上下文。
    逻辑与 generate_response.py 一致。
    """
    # 格式化知识上下文
    soul_context_str = None
    if state.get("soul_context"):
        soul_context_str = retrieval_service.format_context(state["soul_context"])

    # 格式化记忆上下文
    memory_context = state.get("memory_context")
    detailed_history = state.get("detailed_history")
    if detailed_history:
        memory_context = (memory_context or "") + "\n\n详细对话记录:\n" + detailed_history

    # 格式化 preview 摘要
    preview_str = None
    preview = state.get("preview_summary")
    if preview and preview.get("memories"):
        parts = []
        for mem in preview["memories"][:5]:
            summary = mem.get("summary", {})
            if summary.get("key_facts"):
                parts.append(f"- {mem['date']}: {', '.join(summary['key_facts'])}")
        if parts:
            preview_str = "\n".join(parts)

    return {
        "system_prompt": state.get("system_prompt", ""),
        "user_message": state["user_message"],
        "model": state.get("model"),
        "today_messages": state.get("today_messages", []),
        "preview_summary": preview_str,
        "soul_context": soul_context_str,
        "memory_context": memory_context,
        "user_name": state.get("user_name"),
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

        # TTS（可选）— semaphore 限制并发，GPU 服务一次只能处理一个请求
        self.tts_service = TTSService() if settings.tts.enabled else None
        self._tts_semaphore = asyncio.Semaphore(1)

        # 工作流
        self._workflow = None
        self._compiled_graph = None
        self._context_graph = None
        self._deps = None

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
        self._deps = deps
        self._workflow = build_workflow(deps)
        self._compiled_graph = self._workflow.compile()

        # 流式模式用的上下文子图
        context_wf = build_context_workflow(deps)
        self._context_graph = context_wf.compile()

        # TTS 健康检查
        if self.tts_service:
            tts_ok = await self.tts_service.is_available()
            logger.info("TTS service available: %s", tts_ok)

        logger.info("SoulEngine started successfully")

    async def stop(self) -> None:
        """停止引擎"""
        logger.info("Stopping SoulEngine...")
        await self.cache_manager.stop()
        self.persona_manager.close()
        if self.tts_service:
            await self.tts_service.close()
        logger.info("SoulEngine stopped")

    async def chat(
        self,
        user_id: str,
        soul_name: str,
        message: str,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        处理对话请求（非流式，仍用完整 graph）

        返回: {"response": str, "sources": list, "debug_info": dict}
        """
        if self._compiled_graph is None:
            raise SoulBaseError("SoulEngine not started. Call start() first.")

        # 更新用户活跃时间
        await self.user_manager.update_last_active(user_id)

        # 构建初始状态
        initial_state: SoulState = self._build_initial_state(
            user_id, soul_name, message, model
        )

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
        enable_tts: Optional[bool] = None,
        enable_connection_agent: Optional[bool] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        处理对话请求（真实流式）

        三阶段架构：
        1. Context Gathering — 上下文子图收集上下文
        2. True Token Streaming — 直接调用 LLM 流式生成，句子级 TTS
        3. Background Post-Processing — 异步后处理

        Yields: {"event": str, "data": dict}
        """
        if self._context_graph is None:
            yield {"event": "error", "data": {"message": "引擎未启动"}}
            return

        yield {"event": "thinking", "data": {"message": random.choice(_TIPS["start"])}}

        # 更新用户活跃时间
        await self.user_manager.update_last_active(user_id)

        # 构建初始状态
        initial_state: SoulState = self._build_initial_state(
            user_id, soul_name, message, model
        )

        # ── Phase 1: 上下文收集 ──────────────────────────────
        context_state = dict(initial_state)

        try:
            async for node_output in self._context_graph.astream(
                initial_state, stream_mode="updates"
            ):
                node_name = list(node_output.keys())[0]
                node_data = node_output[node_name]

                # 合并状态
                if isinstance(node_data, dict):
                    context_state.update(node_data)

                # yield 进度提示
                tip = _tip(node_name)
                if tip:
                    evt, msg = tip
                    yield {"event": evt, "data": {"message": msg}}

        except Exception as e:
            logger.error("Context gathering failed: %s", e, exc_info=True)
            yield {
                "event": "error",
                "data": {"message": "服务暂时不可用，请稍后重试"},
            }
            return

        # ── greeting 特殊处理（短回复，fake-stream）──────────
        if context_state.get("response"):
            greeting_response = context_state["response"]
            yield {"event": "message_start", "data": {"sentence_id": 0}}
            chunk_size = settings.streaming.chunk_size
            for i in range(0, len(greeting_response), chunk_size):
                yield {
                    "event": "token",
                    "data": {
                        "content": greeting_response[i : i + chunk_size],
                        "sentence_id": 0,
                    },
                }
            yield {"event": "sentence_end", "data": {"sentence_id": 0}}

            # TTS for greeting
            if self.tts_service and enable_tts is not False:
                tts_result = await self._tts_for_sentence(
                    0, greeting_response, soul_name
                )
                if tts_result and tts_result.get("audio_base64"):
                    yield {"event": "audio", "data": {
                        "sentence_id": 0,
                        "audio_base64": tts_result["audio_base64"],
                        "format": tts_result.get("format", "wav"),
                        "duration_seconds": tts_result.get("duration_seconds", 0),
                    }}

            yield {
                "event": "done",
                "data": {
                    "sources": context_state.get("sources", []),
                    "debug_info": context_state.get("debug_info", {}),
                },
            }

            # 后台后处理
            asyncio.create_task(
                self._background_post_process(context_state)
            )
            return

        # ── 准备生成上下文 ────────────────────────────────
        # 注入连接指令（匿名用户）
        if (
            context_state.get("is_anonymous")
            and settings.connection_agent.enabled
            and enable_connection_agent is not False
        ):
            context_state["system_prompt"] = _inject_connection_instructions(
                context_state.get("system_prompt", ""), context_state
            )

        gen_kwargs = _prepare_generation_context(
            context_state, self.retrieval_service
        )

        # ── Phase 2: 真实流式生成 ────────────────────────────
        sentence_id = 0
        current_sentence = ""
        full_response = ""
        tts_tasks: Dict[int, asyncio.Task] = {}
        min_len = settings.streaming.min_sentence_length
        max_bubbles = settings.streaming.max_bubbles

        yield {"event": "message_start", "data": {"sentence_id": 0}}

        try:
            async for token in self.generation_service.generate_stream(
                **gen_kwargs
            ):
                full_response += token
                old_len = len(current_sentence)
                current_sentence += token

                # 检查句子边界（已达上限则不再分割）
                if sentence_id >= max_bubbles - 1:
                    boundary = -1
                else:
                    boundary = find_sentence_boundary(
                        current_sentence, min_len
                    )

                if boundary < 0:
                    # 无断点，直接推送整个 token
                    yield {
                        "event": "token",
                        "data": {
                            "content": token,
                            "sentence_id": sentence_id,
                        },
                    }
                else:
                    # 有断点 — 把 token 拆到正确的气泡
                    split_pos = boundary + 1 - old_len
                    token_before = token[:split_pos] if split_pos > 0 else ""
                    token_after = token[split_pos:] if split_pos < len(token) else ""

                    # 断点前的部分 → 当前气泡
                    if token_before:
                        yield {
                            "event": "token",
                            "data": {
                                "content": token_before,
                                "sentence_id": sentence_id,
                            },
                        }

                    completed = current_sentence[: boundary + 1].strip()
                    remainder = current_sentence[boundary + 1 :]

                    yield {
                        "event": "sentence_end",
                        "data": {"sentence_id": sentence_id},
                    }

                    # 异步 TTS
                    if self.tts_service and enable_tts is not False:
                        tts_tasks[sentence_id] = asyncio.create_task(
                            self._tts_for_sentence(
                                sentence_id, completed, soul_name
                            )
                        )

                    # 开始新气泡
                    sentence_id += 1
                    current_sentence = remainder
                    yield {
                        "event": "message_start",
                        "data": {"sentence_id": sentence_id},
                    }

                    # 断点后的部分 → 新气泡
                    if token_after:
                        yield {
                            "event": "token",
                            "data": {
                                "content": token_after,
                                "sentence_id": sentence_id,
                            },
                        }

        except Exception as e:
            logger.error("Stream generation error: %s", e, exc_info=True)
            if not full_response:
                yield {
                    "event": "error",
                    "data": {"message": "生成回复失败，请稍后重试"},
                }
                return

        # 末尾剩余文本
        if current_sentence.strip():
            yield {
                "event": "sentence_end",
                "data": {"sentence_id": sentence_id},
            }
            if self.tts_service and enable_tts is not False:
                tts_tasks[sentence_id] = asyncio.create_task(
                    self._tts_for_sentence(
                        sentence_id, current_sentence.strip(), soul_name
                    )
                )

        # ── 按序 yield TTS 音频 ─────────────────────────────
        logger.info(
            "Awaiting %d TTS tasks for sentences: %s",
            len(tts_tasks), sorted(tts_tasks.keys()),
        )
        for sid in sorted(tts_tasks.keys()):
            try:
                tts_result = await tts_tasks[sid]
                if tts_result and tts_result.get("audio_base64"):
                    audio_len = len(tts_result["audio_base64"])
                    logger.info(
                        "Yielding audio event: sentence=%d, "
                        "base64_bytes=%d, duration=%.1fs",
                        sid, audio_len,
                        tts_result.get("duration_seconds", 0),
                    )
                    yield {
                        "event": "audio",
                        "data": {
                            "sentence_id": sid,
                            "audio_base64": tts_result["audio_base64"],
                            "format": tts_result.get("format", "wav"),
                            "duration_seconds": tts_result.get(
                                "duration_seconds", 0
                            ),
                        },
                    }
                else:
                    logger.info(
                        "No audio for sentence %d (result=%s)",
                        sid, "None" if tts_result is None else "empty",
                    )
            except Exception as e:
                logger.warning("TTS for sentence %d failed: %s", sid, e)

        # ── done ─────────────────────────────────────────────
        yield {
            "event": "done",
            "data": {
                "sources": context_state.get("sources", []),
                "debug_info": context_state.get("debug_info", {}),
            },
        }

        # ── Phase 3: 后台后处理 ──────────────────────────────
        final_state = {**context_state, "response": full_response}
        asyncio.create_task(self._background_post_process(final_state))

    # ── 辅助方法 ────────────────────────────────────────────

    def _build_initial_state(
        self, user_id: str, soul_name: str, message: str, model: Optional[str]
    ) -> SoulState:
        """构建初始 SoulState"""
        return {
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

    async def _tts_for_sentence(
        self, sentence_id: int, text: str, soul_name: str
    ) -> Optional[Dict[str, Any]]:
        """调用 TTS 合成单个句子的语音（通过 semaphore 串行化，避免压垮 GPU 服务）"""
        try:
            async with self._tts_semaphore:
                return await self.tts_service.synthesize(
                    text=text, soul_name=soul_name
                )
        except Exception as e:
            logger.warning("TTS sentence %d failed: %s", sentence_id, e)
            return None

    async def _background_post_process(self, state: dict) -> None:
        """后台执行后处理节点（保存消息、提取偏好、更新记忆）"""
        try:
            await post_process(state, **self._deps)
            await extract_preferences(state, **self._deps)
            await update_memory(state, **self._deps)
        except Exception as e:
            logger.error(
                "Background post-processing failed: %s", e, exc_info=True
            )
