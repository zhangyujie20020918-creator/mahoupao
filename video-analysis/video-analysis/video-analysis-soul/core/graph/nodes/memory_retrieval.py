"""记忆检索节点"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def memory_retrieval(state: SoulState, **deps) -> dict:
    """
    从 Preview 中检索相关记忆

    1. 用 memory_keywords 在 preview.json 中搜索
    2. 找到相关的 date 和 summary
    3. 如果需要更多细节，标记 needs_detailed_history
    """
    memory_manager = deps.get("memory_manager")

    keywords = state.get("memory_keywords", [])
    if not keywords:
        # 从用户消息中提取关键词
        keywords = state["user_message"].split()

    try:
        matched_entries = await memory_manager.search_memory(
            user_id=state["user_id"],
            persona_name=state["soul_name"],
            keywords=keywords,
        )

        if not matched_entries:
            return {
                "memory_context": None,
                "needs_detailed_history": False,
            }

        # 格式化记忆上下文
        memory_parts = []
        for entry in matched_entries:
            summary = entry.summary
            parts = [f"日期: {entry.date}"]
            if summary.topics_discussed:
                parts.append(f"讨论话题: {', '.join(summary.topics_discussed)}")
            if summary.key_facts:
                parts.append(f"关键事实: {', '.join(summary.key_facts)}")
            if summary.user_preferences:
                parts.append(f"用户偏好: {', '.join(summary.user_preferences)}")
            memory_parts.append("\n".join(parts))

        memory_context = "\n\n".join(memory_parts)

        # 判断是否需要加载详细历史
        needs_detail = state.get("intent") == "recall" and len(matched_entries) > 0

        logger.info(
            f"Memory retrieval: found {len(matched_entries)} entries, "
            f"needs_detail={needs_detail}"
        )

        return {
            "memory_context": memory_context,
            "needs_detailed_history": needs_detail,
        }

    except Exception as e:
        logger.error(f"Memory retrieval failed: {e}")
        return {
            "memory_context": None,
            "needs_detailed_history": False,
        }
