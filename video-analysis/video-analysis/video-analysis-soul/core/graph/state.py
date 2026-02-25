"""LangGraph 状态定义"""

from typing import Dict, List, Literal, Optional, TypedDict


class SoulState(TypedDict):
    """工作流状态"""

    # 输入
    user_id: str
    soul_name: str
    user_message: str
    model: str

    # 用户信息
    user_name: str
    is_anonymous: bool
    is_registered: bool
    user_preferences: Dict
    turn_count: int

    # 分析结果
    intent: Literal["greeting", "question", "recall", "chat", "farewell"]
    needs_soul_knowledge: bool
    needs_memory_recall: bool
    memory_keywords: List[str]

    # 检索结果
    soul_context: List[Dict]
    memory_context: Optional[str]
    detailed_history: Optional[str]
    needs_detailed_history: bool

    # 当前上下文
    today_messages: List[Dict]
    preview_summary: Dict
    system_prompt: str

    # 输出
    response: str
    sources: List[Dict]

    # 调试信息
    debug_info: Dict
