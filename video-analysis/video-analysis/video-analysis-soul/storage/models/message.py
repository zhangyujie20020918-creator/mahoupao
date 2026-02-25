"""消息数据模型"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from common.utils.datetime import now


class SourceReference(BaseModel):
    """引用来源"""

    video: str = ""
    segment: int = 0
    text: str = ""
    relevance: float = 0.0


class Message(BaseModel):
    """单条消息"""

    id: str
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=now)
    sources: List[SourceReference] = []


class DailyConversation(BaseModel):
    """每日对话记录"""

    date: str
    user_id: str
    blogger: str
    messages: List[Message] = []
    message_count: int = 0
