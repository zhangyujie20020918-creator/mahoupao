"""Persona 接口"""

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import BaseResponse
from api.schemas.persona import PersonaListResponse, PersonaResponse

router = APIRouter()


@router.get("/bloggers")
async def list_bloggers(request: Request) -> BaseResponse:
    """可用博主列表"""
    engine = request.app.state.engine
    personas = engine.persona_manager.list_available_personas()
    return BaseResponse(
        data=PersonaListResponse(
            personas=[PersonaResponse(**p) for p in personas]
        )
    )


@router.get("/bloggers/{name}")
async def get_blogger(name: str, request: Request) -> BaseResponse:
    """获取博主详情"""
    engine = request.app.state.engine
    try:
        persona = engine.persona_manager.load_persona(name)
        return BaseResponse(
            data={
                "name": persona.persona_name,
                "type": persona.persona_type.value,
                "speaking_style": persona.speaking_style,
                "topic_expertise": persona.topic_expertise,
                "personality_traits": persona.personality_traits,
                "common_phrases": persona.common_phrases,
            }
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Persona not found: {name}")
