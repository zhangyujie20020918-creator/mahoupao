"""打招呼流程节点"""

from datetime import datetime
from typing import Optional

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


def _categorize_absence(last_active: Optional[datetime]) -> str:
    """分类用户离开时长"""
    if last_active is None:
        return "new_user"

    hours = (datetime.now() - last_active).total_seconds() / 3600
    if hours < 24:
        return "same_day"
    elif hours < 72:
        return "short_absence"
    else:
        return "long_absence"


async def greeting_flow(state: SoulState, **deps) -> dict:
    """
    打招呼流程：
    1. 判断用户状态（新用户/今日首次/隔天/长时间未登录）
    2. 生成个性化问候
    """
    user_manager = deps.get("user_manager")
    generation_service = deps.get("generation_service")

    user = await user_manager.get_user(state["user_id"])
    absence_category = _categorize_absence(user.last_active)

    # 构建打招呼 prompt
    user_name = state.get("user_name", "朋友")
    system_prompt = state.get("system_prompt", "")

    greeting_instruction = f"""你正在和{user_name}打招呼。
用户状态: {absence_category}
{'这是新用户，第一次来找你聊天。' if absence_category == 'new_user' else ''}
{'今天已经聊过了，用户又回来了。' if absence_category == 'same_day' else ''}
{'用户几天没来了，表示关心。' if absence_category == 'short_absence' else ''}
{'用户很久没来了，表示热情欢迎。' if absence_category == 'long_absence' else ''}

请用你的风格打个招呼，简短自然。"""

    response = await generation_service.generate(
        system_prompt=system_prompt,
        user_message=greeting_instruction,
        model=state.get("model"),
    )

    return {
        "response": response,
        "sources": [],
    }
