"""Persona 数据模型"""

from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, field_validator


class PersonaType(str, Enum):
    INFLUENCER = "influencer"   # 网红/博主
    CELEBRITY = "celebrity"     # 明星
    EXPERT = "expert"           # 专家
    CHARACTER = "character"     # 虚拟角色
    HISTORICAL = "historical"   # 历史人物
    CUSTOM = "custom"           # 自定义


class PersonaMetadata(BaseModel):
    """Persona 元数据 - 映射自 maker 的 persona.json"""

    persona_name: str
    persona_type: PersonaType = PersonaType.INFLUENCER
    speaking_style: str = ""
    common_phrases: List[str] = []
    topic_expertise: List[str] = []
    personality_traits: List[str] = []
    tone: str = ""
    target_audience: str = ""
    content_patterns: str = ""  # maker 输出为 string
    system_prompt: str = ""

    # 内部元数据
    chroma_db_path: Optional[str] = None
    output_dir: Optional[str] = None
    video_count: int = 0  # optimized_texts 中的视频数量
    knowledge_count: int = 0  # ChromaDB 中的文档数量

    @field_validator("content_patterns", mode="before")
    @classmethod
    def coerce_content_patterns(cls, v):
        """兼容 list 和 string 两种输入"""
        if isinstance(v, list):
            return "\n".join(v)
        return v or ""
