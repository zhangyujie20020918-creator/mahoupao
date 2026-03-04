"""Auth 认证路由"""

from typing import Optional

from fastapi import APIRouter, Query, Request

from api.schemas.auth import (
    AuthUserResponse,
    ChallengeResponse,
    RegisterRequest,
    SecretCatalogResponse,
    SecretQuestionItem,
    UpgradeRequest,
    VerifyPassphraseRequest,
    VerifyResult,
    VerifySecretRequest,
)
from api.schemas.common import BaseResponse
from common.logger import get_logger
from storage.models.secret_catalog import get_questions

logger = get_logger(__name__)

router = APIRouter(prefix="/auth")


def _user_to_auth_response(user) -> AuthUserResponse:
    return AuthUserResponse(
        id=user.id,
        name=user.name,
        gender=user.gender,
        is_anonymous=user.is_anonymous,
        is_registered=user.is_registered,
        has_passphrase=user.passphrase_hash is not None,
        secret_count=len(user.secrets),
        created_at=user.created_at,
        last_active=user.last_active,
    )


@router.post("/anonymous")
async def create_anonymous(request: Request) -> BaseResponse:
    """创建匿名用户"""
    engine = request.app.state.engine
    user = await engine.user_manager.create_anonymous()
    logger.info(f"Anonymous user created: {user.id}")
    return BaseResponse(data=_user_to_auth_response(user).model_dump(mode="json"))


@router.post("/register")
async def register(body: RegisterRequest, request: Request) -> BaseResponse:
    """完整注册"""
    engine = request.app.state.engine
    user = await engine.user_manager.register_user(
        name=body.name,
        gender=body.gender,
        passphrase=body.passphrase,
        secrets=[s for s in body.secrets],
    )
    logger.info(f"User registered: {user.id} ({user.name})")
    return BaseResponse(data=_user_to_auth_response(user).model_dump(mode="json"))


@router.post("/upgrade")
async def upgrade(body: UpgradeRequest, request: Request) -> BaseResponse:
    """匿名用户升级为注册用户"""
    engine = request.app.state.engine
    user = await engine.user_manager.upgrade_user(
        user_id=body.user_id,
        name=body.name,
        gender=body.gender,
        passphrase=body.passphrase,
        secrets=[s for s in body.secrets],
    )
    logger.info(f"User upgraded: {user.id} ({user.name})")
    return BaseResponse(data=_user_to_auth_response(user).model_dump(mode="json"))


@router.post("/verify/passphrase")
async def verify_passphrase(
    body: VerifyPassphraseRequest, request: Request
) -> BaseResponse:
    """口令验证"""
    engine = request.app.state.engine
    ok = await engine.user_manager.verify_passphrase(body.user_id, body.passphrase)
    result = VerifyResult(
        verified=ok,
        user_id=body.user_id if ok else None,
        message="验证通过" if ok else "口令不正确",
    )
    return BaseResponse(data=result.model_dump())


@router.get("/verify/challenge")
async def get_challenge(user_id: str, request: Request) -> BaseResponse:
    """获取随机秘密挑战题"""
    engine = request.app.state.engine
    challenge = await engine.user_manager.get_random_challenge(user_id)
    return BaseResponse(data=challenge)


@router.post("/verify/secret")
async def verify_secret(
    body: VerifySecretRequest, request: Request
) -> BaseResponse:
    """验证小秘密答案"""
    engine = request.app.state.engine
    ok = await engine.user_manager.verify_secret(
        body.user_id, body.question_id, body.answer
    )
    result = VerifyResult(
        verified=ok,
        user_id=body.user_id if ok else None,
        message="验证通过" if ok else "答案不正确",
    )
    return BaseResponse(data=result.model_dump())


@router.get("/secrets/catalog")
async def secrets_catalog(
    gender: Optional[str] = Query(None, description="male / female / 不传返回全部"),
) -> BaseResponse:
    """获取小秘密题目目录"""
    questions = get_questions(gender)
    items = [
        SecretQuestionItem(
            id=q.id, question=q.question, gender=q.gender, category=q.category
        )
        for q in questions
    ]
    return BaseResponse(data=SecretCatalogResponse(questions=items).model_dump())


@router.get("/user/{user_id}")
async def get_user_info(user_id: str, request: Request) -> BaseResponse:
    """获取用户信息（含注册状态）"""
    engine = request.app.state.engine
    user = await engine.user_manager.get_user(user_id)
    return BaseResponse(data=_user_to_auth_response(user).model_dump(mode="json"))
