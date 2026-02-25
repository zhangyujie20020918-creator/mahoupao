"""Persona 接口"""

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import BaseResponse
from api.schemas.persona import PersonaListResponse, PersonaResponse

router = APIRouter()


@router.get("/souls")
async def list_souls(request: Request) -> BaseResponse:
    """可用列表"""
    engine = request.app.state.engine
    personas = engine.persona_manager.list_available_personas()
    return BaseResponse(
        data=PersonaListResponse(
            personas=[PersonaResponse(**p) for p in personas]
        )
    )


@router.get("/souls/{name}")
async def get_soul(name: str, request: Request) -> BaseResponse:
    """获取详情"""
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
