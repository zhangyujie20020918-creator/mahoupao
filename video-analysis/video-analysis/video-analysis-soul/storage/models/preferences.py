"""用户偏好模型 — 跨的用户综合画像"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from common.utils.datetime import now


class MoodEntry(BaseModel):
    """情绪记录"""

    date: str
    mood: str
    context: str = ""


class UserPreferences(BaseModel):
    """跨的用户综合画像"""

    user_id: str
    last_updated: datetime = Field(default_factory=now)

    # 基础信息
    interests: List[str] = []
    visit_motivation: Optional[str] = None
    personality_type: Optional[str] = None
    communication_style: Optional[str] = None

    # 动态偏好
    recent_topics: List[str] = []
    mood_history: List[MoodEntry] = []
    knowledge_level: Dict[str, str] = {}

    # 收集进度
    collection_progress: Dict[str, bool] = {}
