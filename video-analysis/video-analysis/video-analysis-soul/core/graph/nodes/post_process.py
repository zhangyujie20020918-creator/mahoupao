"""后处理节点 - 保存消息"""

import uuid

from core.graph.state import SoulState
from common.logger import get_logger
from storage.models.message import Message, SourceReference

logger = get_logger(__name__)


async def post_process(state: SoulState, **deps) -> dict:
    """
    保存用户消息和 AI 回复到今日对话
    """
    memory_manager = deps.get("memory_manager")

    user_id = state["user_id"]
    soul_name = state["soul_name"]

    # 保存用户消息
    user_msg = Message(
        id=f"msg-{uuid.uuid4().hex[:8]}",
        role="user",
        content=state["user_message"],
    )
    await memory_manager.add_message(user_id, soul_name, user_msg)

    # 保存 AI 回复
    sources = [
        SourceReference(**s) for s in (state.get("sources") or [])
    ]
    ai_msg = Message(
        id=f"msg-{uuid.uuid4().hex[:8]}",
        role="assistant",
        content=state.get("response", ""),
        sources=sources,
    )
    conv = await memory_manager.add_message(user_id, soul_name, ai_msg)

    logger.info(
        f"Saved messages: user_id={user_id}, soul={soul_name}, "
        f"total_messages={conv.message_count}"
    )

    return {}
