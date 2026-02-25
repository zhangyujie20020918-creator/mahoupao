"""用户管理器"""

import uuid
from typing import List, Optional

from common.exceptions import UserAlreadyExistsError, UserNotFoundError
from common.logger import get_logger
from common.utils.datetime import now
from storage.models.user import UserProfile
from storage.repositories.user_repository import UserRepository

logger = get_logger(__name__)


class UserManager:
    """用户管理"""

    def __init__(self):
        self._repo = UserRepository()

    async def list_users(self) -> List[UserProfile]:
        """获取所有用户"""
        return await self._repo.get_all()

    async def get_user(self, user_id: str) -> UserProfile:
        """获取用户，不存在则抛异常"""
        user = await self._repo.get_by_id(user_id)
        if not user:
            raise UserNotFoundError(f"User not found: {user_id}")
        return user

    async def create_user(self, name: str) -> UserProfile:
        """创建新用户"""
        user_id = str(uuid.uuid4())
        profile = UserProfile(id=user_id, name=name)
        return await self._repo.create(profile)

    async def delete_user(self, user_id: str) -> bool:
        """删除用户"""
        result = await self._repo.delete(user_id)
        if not result:
            raise UserNotFoundError(f"User not found: {user_id}")
        return True

    async def update_last_active(self, user_id: str) -> UserProfile:
        """更新用户最后活跃时间"""
        user = await self.get_user(user_id)
        user.last_active = now()
        return await self._repo.update(user)
