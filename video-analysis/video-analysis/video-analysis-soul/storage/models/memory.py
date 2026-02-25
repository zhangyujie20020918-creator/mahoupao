"""记忆数据模型"""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from common.utils.datetime import now


class PersonMention(BaseModel):
    name: str
    relation: str = ""
    context: str = ""


class EventRecord(BaseModel):
    what: str
    when: str = ""
    result: str = ""


class ObjectRecord(BaseModel):
    name: str
    context: str = ""
    owner: str = ""


class MemorySummary(BaseModel):
    """每日对话摘要"""

    topics_discussed: List[str] = []
    people_mentioned: List[PersonMention] = []
    places: List[str] = []
    events: List[EventRecord] = []
    emotions: List[str] = []
    objects: List[ObjectRecord] = []
    user_preferences: List[str] = []
    key_facts: List[str] = []


class MemoryEntry(BaseModel):
    """单条记忆条目"""

    date: str
    blogger: str
    summary: MemorySummary = MemorySummary()


class Preview(BaseModel):
    """记忆总览（跨天累积）"""

    user_id: str
    last_updated: datetime = Field(default_factory=now)
    summary_version: int = 1
    memories: List[MemoryEntry] = []


class LongTermFact(BaseModel):
    """长期记忆事实"""

    fact: str
    source: str = ""  # 来源 (哪次对话)
    created_at: datetime = Field(default_factory=now)
    confidence: float = 1.0


class LongTermMemory(BaseModel):
    """长期记忆"""

    user_id: str
    facts: List[LongTermFact] = []
    last_updated: datetime = Field(default_factory=now)
