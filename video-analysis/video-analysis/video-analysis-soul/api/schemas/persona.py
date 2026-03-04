"""Persona Schema"""

from typing import List, Optional

from pydantic import BaseModel


class PersonaResponse(BaseModel):
    """Persona 信息"""

    name: str
    has_knowledge_base: bool = False
    has_system_prompt: bool = False


class PersonaListResponse(BaseModel):
    """Persona 列表"""

    personas: List[PersonaResponse] = []
