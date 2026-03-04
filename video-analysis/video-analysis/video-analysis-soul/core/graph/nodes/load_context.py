"""加载上下文节点 - 加载用户数据和 Persona 数据"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def load_context(state: SoulState, **deps) -> dict:
    """
    加载上下文：
    1. 加载 Persona system_prompt
    2. 加载今日对话历史
    3. 加载 Preview 总览
    """
    persona_manager = deps.get("persona_manager")
    memory_manager = deps.get("memory_manager")
    user_manager = deps.get("user_manager")

    user_id = state["user_id"]
    soul_name = state["soul_name"]

    # 加载 Persona
    persona = persona_manager.load_persona(soul_name)
    system_prompt = persona.system_prompt

    # 加载用户信息
    user = await user_manager.get_user(user_id)
    user_name = user.name
    is_anonymous = user.is_anonymous
    is_registered = user.is_registered

    # 加载用户偏好（仅匿名用户需要）
    user_preferences = {}
    if is_anonymous:
        preferences_repo = deps.get("preferences_repo")
        if preferences_repo:
            prefs = await preferences_repo.get(user_id)
            user_preferences = prefs.model_dump(mode="json")

    # 加载今日对话
    conv = await memory_manager.get_today_conversation(user_id, soul_name)
    today_messages = [
        {"role": m.role, "content": m.content}
        for m in conv.messages
    ]

    # 加载 Preview
    preview = await memory_manager.get_preview(user_id, soul_name)
    preview_summary = {}
    if preview and preview.memories:
        preview_summary = preview.model_dump(mode="json")

    logger.info(
        f"Loaded context: user={user_name}, persona={soul_name}, "
        f"today_msgs={len(today_messages)}, memories={len(preview.memories) if preview else 0}, "
        f"anonymous={is_anonymous}"
    )

    return {
        "system_prompt": system_prompt,
        "user_name": user_name,
        "is_anonymous": is_anonymous,
        "is_registered": is_registered,
        "user_preferences": user_preferences,
        "turn_count": len(today_messages),
        "today_messages": today_messages,
        "preview_summary": preview_summary,
    }
