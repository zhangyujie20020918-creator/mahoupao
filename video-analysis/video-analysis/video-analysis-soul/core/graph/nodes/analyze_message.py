"""意图/情绪分析节点"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def analyze_message(state: SoulState, **deps) -> dict:
    """
    分析用户消息的意图和情绪

    使用轻量模型 (gemini-2.0-flash-lite) 快速分析：
    - greeting: 打招呼
    - question: 专业问题
    - recall: 提及过去
    - chat: 日常闲聊
    - farewell: 告别
    """
    analysis_service = deps.get("analysis_service")

    result = await analysis_service.analyze_intent(
        user_message=state["user_message"],
        today_messages=state.get("today_messages", []),
        preview_summary=state.get("preview_summary"),
    )

    logger.info(
        f"Intent analysis: intent={result.get('intent')}, "
        f"knowledge={result.get('needs_soul_knowledge')}, "
        f"memory={result.get('needs_memory_recall')}"
    )

    return {
        "intent": result.get("intent", "chat"),
        "needs_soul_knowledge": result.get("needs_soul_knowledge", False),
        "needs_memory_recall": result.get("needs_memory_recall", False),
        "memory_keywords": result.get("memory_keywords", []),
        "debug_info": {
            **(state.get("debug_info") or {}),
            "intent_analysis": result,
        },
    }
