"""连接助手节点 - 为匿名用户改写回复，融入关系建立元素"""

import json

from core.graph.state import SoulState
from common.config import settings, BASE_DIR
from common.logger import get_logger

logger = get_logger(__name__)

# 加载 prompt 模板（模块级，只读一次）
_PROMPT_PATH = BASE_DIR / "config" / "prompts" / "connection_agent.txt"
_PROMPT_TEMPLATE = (
    _PROMPT_PATH.read_text(encoding="utf-8") if _PROMPT_PATH.exists() else ""
)


def _get_missing_dimensions(user_preferences: dict) -> list:
    """计算还未收集到的维度"""
    progress = user_preferences.get("collection_progress", {})
    all_dims = settings.connection_agent.dimensions
    return [d for d in all_dims if not progress.get(d)]


def _pick_target_dimension(missing: list) -> str:
    """选择本轮要探索的维度（取第一个未收集的）"""
    return missing[0] if missing else "recent_topics"


async def connection_rewrite(state: SoulState, **deps) -> dict:
    """
    为匿名用户改写回复。

    对于非匿名用户，直接返回空 dict（NO-OP）。
    """
    # NO-OP guard
    if not state.get("is_anonymous", False):
        return {}

    if not settings.connection_agent.enabled:
        return {}

    if not _PROMPT_TEMPLATE:
        logger.warning("connection_agent.txt prompt not found, skipping rewrite")
        return {}

    llm_service = deps.get("llm_service")
    original_response = state.get("response", "")
    if not original_response:
        return {}

    user_preferences = state.get("user_preferences", {})
    turn_count = state.get("turn_count", 0)

    missing_dims = _get_missing_dimensions(user_preferences)
    target_dim = _pick_target_dimension(missing_dims)

    # 格式化今日对话为文本
    today_messages = state.get("today_messages", [])
    conversation_text = "\n".join(
        f"{'用户' if m.get('role') == 'user' else ''}: {m.get('content', '')}"
        for m in today_messages[-10:]
    )

    # 格式化偏好摘要
    prefs_summary = "暂无"
    if user_preferences:
        filtered = {
            k: v for k, v in user_preferences.items()
            if k in (
                "interests", "visit_motivation", "personality_type",
                "communication_style", "recent_topics",
            ) and v
        }
        if filtered:
            prefs_summary = json.dumps(filtered, ensure_ascii=False)

    # 填充模板
    prompt = _PROMPT_TEMPLATE.format(
        preferences=prefs_summary,
        turn_count=turn_count,
        missing_dimensions="、".join(missing_dims) if missing_dims else "无",
        target_dimension=target_dim,
        original_response=original_response,
        conversation=conversation_text or "（首轮对话）",
        nudge_threshold=settings.connection_agent.nudge_threshold,
    )

    try:
        rewritten = await llm_service.analyze(prompt)
        rewritten = rewritten.strip()
        if rewritten:
            logger.info(
                f"Connection rewrite: {len(original_response)} -> {len(rewritten)} chars, "
                f"target_dim={target_dim}, turn={turn_count}"
            )
            return {
                "response": rewritten,
                "debug_info": {
                    **(state.get("debug_info") or {}),
                    "connection_agent": {
                        "original_length": len(original_response),
                        "rewritten_length": len(rewritten),
                        "target_dimension": target_dim,
                        "missing_dimensions": missing_dims,
                        "turn_count": turn_count,
                    },
                },
            }
    except Exception as e:
        logger.error(f"Connection rewrite failed, keeping original: {e}")

    return {}
