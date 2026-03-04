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

    # 根据用户状态构建不同的打招呼指引
    status_guides = {
        "new_user": f"这是{user_name}第一次来找你聊天。用热情但不过度的方式欢迎，可以简单介绍自己，让对方感到轻松。不要问太多问题，先让对方适应。",
        "same_day": f"{user_name}今天已经和你聊过了，现在又回来了。用轻松随意的语气，像老朋友回来继续聊一样，可以接上之前的话题或者简单问一句。",
        "short_absence": f"{user_name}有几天没来了。表达一下你注意到对方有段时间没来，自然地表示关心，但不要夸张。",
        "long_absence": f"{user_name}很久没来了。热情欢迎回来，可以调侃一下对方'消失'了这么久，语气亲切自然。",
    }

    greeting_instruction = f"""{status_guides.get(absence_category, '')}

要求：
- 用你自己的说话风格和口头禅，保持人设一致
- 简短自然，1-2句话即可，不要长篇大论
- 像真人聊天一样，不要过于正式
- 可以使用你习惯的开场白"""

    response = await generation_service.generate(
        system_prompt=system_prompt,
        user_message=greeting_instruction,
        model=state.get("model"),
    )

    return {
        "response": response,
        "sources": [],
    }
