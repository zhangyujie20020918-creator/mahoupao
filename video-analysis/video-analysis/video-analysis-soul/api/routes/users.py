"""用户接口"""

from fastapi import APIRouter, HTTPException, Request

from api.schemas.common import BaseResponse
from api.schemas.user import UserCreate, UserListResponse, UserResponse
from common.exceptions import UserNotFoundError

router = APIRouter()


@router.get("/users")
async def list_users(request: Request) -> BaseResponse:
    """用户列表"""
    engine = request.app.state.engine
    users = await engine.user_manager.list_users()
    return BaseResponse(
        data=UserListResponse(
            users=[
                UserResponse(
                    id=u.id,
                    name=u.name,
                    created_at=u.created_at,
                    last_active=u.last_active,
                )
                for u in users
            ]
        )
    )


@router.post("/users")
async def create_user(body: UserCreate, request: Request) -> BaseResponse:
    """创建用户"""
    engine = request.app.state.engine
    user = await engine.user_manager.create_user(body.name)
    return BaseResponse(
        message="User created",
        data=UserResponse(
            id=user.id,
            name=user.name,
            created_at=user.created_at,
            last_active=user.last_active,
        ),
    )


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> BaseResponse:
    """删除用户"""
    engine = request.app.state.engine
    try:
        await engine.user_manager.delete_user(user_id)
        return BaseResponse(message="User deleted")
    except UserNotFoundError:
        raise HTTPException(status_code=404, detail=f"User not found: {user_id}")
