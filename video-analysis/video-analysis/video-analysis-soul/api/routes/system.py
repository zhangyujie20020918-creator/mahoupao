"""系统接口"""

from fastapi import APIRouter, Request

from api.schemas.common import BaseResponse
from common.config import settings

router = APIRouter()


@router.get("/status")
async def get_status(request: Request) -> BaseResponse:
    """服务状态"""
    engine = request.app.state.engine
    return BaseResponse(
        data={
            "status": "running",
            "active_sessions": engine.session_manager.active_sessions,
            "port": settings.port,
        }
    )


@router.get("/models")
async def get_models() -> BaseResponse:
    """可用模型列表"""
    return BaseResponse(
        data={
            "models": settings.llm.available_models,
            "default": settings.llm.default_model,
        }
    )
