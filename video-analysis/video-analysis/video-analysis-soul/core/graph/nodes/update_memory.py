"""更新记忆节点 - 定期触发 Preview 总结"""

import json
import re

from core.graph.state import SoulState
from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)


async def update_memory(state: SoulState, **deps) -> dict:
    """
    检查是否需要触发 Preview 总结

    触发条件: 每 N 条消息触发一次
    """
    memory_manager = deps.get("memory_manager")
    llm_service = deps.get("llm_service")

    user_id = state["user_id"]
    blogger_name = state["blogger_name"]

    # 获取今日对话
    conv = await memory_manager.get_today_conversation(user_id, blogger_name)
    trigger_count = settings.memory.preview.summary_trigger_messages

    # 检查是否需要总结
    if trigger_count > 0 and conv.message_count > 0 and conv.message_count % trigger_count == 0:
        logger.info(
            f"Triggering preview summary: {conv.message_count} messages reached"
        )
        await _generate_preview_summary(
            memory_manager, llm_service, user_id, blogger_name, conv.messages
        )

    return {}


async def _generate_preview_summary(
    memory_manager, llm_service, user_id, blogger_name, messages
):
    """生成 Preview 总结"""
    from common.config import BASE_DIR
    from storage.models.memory import MemorySummary

    # 加载 prompt 模板
    prompt_path = BASE_DIR / "config" / "prompts" / "preview_summary.txt"
    if prompt_path.exists():
        prompt_template = prompt_path.read_text(encoding="utf-8")
    else:
        prompt_template = _default_summary_prompt()

    # 格式化对话内容
    conv_text = "\n".join(
        f"{'用户' if m.role == 'user' else '博主'}: {m.content}"
        for m in messages[-20:]  # 最近20条
    )

    full_prompt = f"{prompt_template}\n\n{conv_text}"

    try:
        result_text = await llm_service.summarize(full_prompt)
        # 解析 JSON
        result_text = result_text.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)```", result_text, re.DOTALL)
        if match:
            result_text = match.group(1).strip()
        summary_data = json.loads(result_text)
        summary = MemorySummary(**summary_data)
        await memory_manager.update_preview(user_id, blogger_name, summary)
        logger.info(f"Preview summary updated for user={user_id}, persona={blogger_name}")
    except Exception as e:
        logger.error(f"Preview summary failed: {e}")


def _default_summary_prompt() -> str:
    return """你是一个记忆助手，负责总结用户和博主的对话。

请从以下对话中提取关键信息，格式如下：
{
  "topics_discussed": ["讨论的主题"],
  "people_mentioned": [
    {"name": "人名", "relation": "与用户的关系", "context": "提及场景"}
  ],
  "places": ["地名"],
  "events": [
    {"what": "事件描述", "when": "时间", "result": "结果"}
  ],
  "emotions": ["用户表现出的情绪"],
  "objects": [
    {"name": "物品名", "context": "使用场景", "owner": "所属人"}
  ],
  "user_preferences": ["用户偏好"],
  "key_facts": ["重要事实"]
}

注意：
- 保留细节但不要过于冗长
- 人名、地名、物品名要准确
- 情绪要结合上下文描述
- 如果没有某类信息，返回空数组

今天的对话："""
