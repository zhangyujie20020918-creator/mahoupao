"""偏好提取节点 - 从对话中提取匿名用户偏好并保存"""

import json
import re

from core.graph.state import SoulState
from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

_EXTRACTION_PROMPT = """从以下对话中提取用户画像信息。只提取你确信的内容，不要猜测。

请返回 JSON 格式：
{
  "interests": ["兴趣1", "兴趣2"],
  "visit_motivation": "来访动机（字符串或null）",
  "personality_type": "性格类型（字符串或null）",
  "communication_style": "沟通风格（字符串或null）",
  "recent_topics": ["最近话题1", "话题2"],
  "knowledge_level": {"领域": "水平"}
}

如果某个维度无法提取，设为 null 或空数组。

对话内容：
"""


async def extract_preferences(state: SoulState, **deps) -> dict:
    """
    从对话中提取用户偏好并保存。

    仅对匿名用户执行。对已注册用户直接返回空 dict。
    """
    if not state.get("is_anonymous", False):
        return {}

    if not settings.connection_agent.enabled:
        return {}

    llm_service = deps.get("llm_service")
    preferences_repo = deps.get("preferences_repo")

    if not preferences_repo:
        return {}

    user_id = state["user_id"]
    today_messages = state.get("today_messages", [])

    # 包含当前轮的用户消息和 AI 回复
    current_messages = today_messages + [
        {"role": "user", "content": state.get("user_message", "")},
        {"role": "assistant", "content": state.get("response", "")},
    ]

    # 只在足够的对话后提取（至少 2 轮，即 4 条消息）
    if len(current_messages) < 4:
        return {}

    # 不是每轮都提取 — 每 3 轮提取一次，减少 LLM 调用
    turn_count = len(current_messages) // 2
    if turn_count % 3 != 0 and turn_count != 2:
        return {}

    conv_text = "\n".join(
        f"{'用户' if m.get('role') == 'user' else ''}: {m.get('content', '')}"
        for m in current_messages[-12:]
    )

    try:
        result_text = await llm_service.analyze(
            f"{_EXTRACTION_PROMPT}{conv_text}"
        )
        # 解析 JSON
        result_text = result_text.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", result_text, re.DOTALL)
        if match:
            result_text = match.group(1).strip()

        extracted = json.loads(result_text)

        # 合并保存
        updated_prefs = await preferences_repo.merge_from_conversation(
            user_id, extracted
        )

        logger.info(
            f"Preferences extracted for user={user_id}: "
            f"interests={len(updated_prefs.interests)}, "
            f"progress={updated_prefs.collection_progress}"
        )

        return {
            "user_preferences": updated_prefs.model_dump(mode="json"),
        }
    except Exception as e:
        logger.error(f"Preference extraction failed: {e}")
        return {}
