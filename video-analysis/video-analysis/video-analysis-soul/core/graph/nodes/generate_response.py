"""生成回复节点"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def generate_response(state: SoulState, **deps) -> dict:
    """
    组装最终 prompt，调用 LLM 生成回复
    """
    generation_service = deps.get("generation_service")
    retrieval_service = deps.get("retrieval_service")

    # 格式化博主知识上下文
    blogger_context_str = None
    if state.get("blogger_context"):
        blogger_context_str = retrieval_service.format_context(state["blogger_context"])

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

    # 生成回复
    response = await generation_service.generate(
        system_prompt=state.get("system_prompt", ""),
        user_message=state["user_message"],
        model=state.get("model"),
        today_messages=state.get("today_messages", []),
        preview_summary=preview_str,
        blogger_context=blogger_context_str,
        memory_context=memory_context,
        user_name=state.get("user_name"),
    )

    logger.info(f"Generated response: {len(response)} chars")

    return {"response": response}
