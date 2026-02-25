"""详细历史加载节点"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def load_detail_history(state: SoulState, **deps) -> dict:
    """
    按需加载特定日期的详细对话

    只在 memory_context 不够详细时触发
    """
    memory_manager = deps.get("memory_manager")

    # 从 memory_context 中提取需要加载的日期
    memory_context = state.get("memory_context", "")
    if not memory_context:
        return {"detailed_history": None}

    # 尝试从匹配的记忆中提取日期
    dates = []
    for line in memory_context.split("\n"):
        if line.startswith("日期: "):
            dates.append(line.replace("日期: ", "").strip())

    if not dates:
        return {"detailed_history": None}

    # 加载最相关日期的详细对话（最多3天）
    detail_parts = []
    for date_str in dates[:3]:
        conv = await memory_manager.get_conversation_by_date(
            user_id=state["user_id"],
            persona_name=state["blogger_name"],
            date=date_str,
        )
        if conv and conv.messages:
            lines = [f"--- {date_str} 的对话 ---"]
            for msg in conv.messages[-10:]:  # 最近10条
                role = "用户" if msg.role == "user" else "博主"
                lines.append(f"{role}: {msg.content}")
            detail_parts.append("\n".join(lines))

    detailed_history = "\n\n".join(detail_parts) if detail_parts else None

    logger.info(f"Loaded detail history for {len(dates)} dates")

    return {"detailed_history": detailed_history}
