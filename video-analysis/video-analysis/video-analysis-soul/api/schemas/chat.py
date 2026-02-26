"""Chat Schema"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ChatRequest(BaseModel):
    """对话请求"""

    user_id: str
    soul: str
    message: str
    model: Optional[str] = None
    enable_tts: Optional[bool] = None
    enable_connection_agent: Optional[bool] = None


class ChatEvent(BaseModel):
    """SSE 事件"""

    event: str  # "thinking" | "searching" | "message_start" | "token" | "sentence_end" | "audio" | "done" | "error"
    data: Dict[str, Any] = {}
