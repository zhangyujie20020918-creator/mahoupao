"""用户数据读写"""

import json
from pathlib import Path
from typing import Dict, List, Optional

from common.config import settings
from common.logger import get_logger
from common.utils.async_utils import read_json, write_json
from storage.models.user import UserProfile

logger = get_logger(__name__)


class UserRepository:
    """用户数据仓库"""

    def __init__(self):
        self._base_dir = settings.soul_data_dir / "users"
        self._index_path = self._base_dir / "index.json"
        self._base_dir.mkdir(parents=True, exist_ok=True)

    async def get_all(self) -> List[UserProfile]:
        """获取所有用户"""
        if not self._index_path.exists():
            return []
        data = await read_json(self._index_path)
        return [UserProfile(**u) for u in data.get("users", [])]

    async def get_by_id(self, user_id: str) -> Optional[UserProfile]:
        """根据 ID 获取用户"""
        profile_path = self._base_dir / user_id / "profile.json"
        if not profile_path.exists():
            return None
        data = await read_json(profile_path)
        return UserProfile(**data)

    async def create(self, profile: UserProfile) -> UserProfile:
        """创建用户"""
        user_dir = self._base_dir / profile.id
        user_dir.mkdir(parents=True, exist_ok=True)

        # 保存 profile
        await write_json(user_dir / "profile.json", profile.model_dump(mode="json"))

        # 更新索引
        await self._update_index(profile)

        logger.info(f"Created user: {profile.id} ({profile.name})")
        return profile

    async def update(self, profile: UserProfile) -> UserProfile:
        """更新用户"""
        user_dir = self._base_dir / profile.id
        await write_json(user_dir / "profile.json", profile.model_dump(mode="json"))
        await self._update_index(profile)
        return profile

    async def delete(self, user_id: str) -> bool:
        """删除用户"""
        user_dir = self._base_dir / user_id
        if not user_dir.exists():
            return False

        import shutil
        shutil.rmtree(user_dir)

        # 更新索引
        await self._remove_from_index(user_id)
        logger.info(f"Deleted user: {user_id}")
        return True

    async def _update_index(self, profile: UserProfile) -> None:
        """更新用户索引"""
        if self._index_path.exists():
            data = await read_json(self._index_path)
        else:
            data = {"users": []}

        users = data.get("users", [])
        # 替换或添加
        users = [u for u in users if u.get("id") != profile.id]
        users.append(profile.model_dump(mode="json"))
        data["users"] = users

        await write_json(self._index_path, data)

    async def _remove_from_index(self, user_id: str) -> None:
        """从索引中移除用户"""
        if not self._index_path.exists():
            return
        data = await read_json(self._index_path)
        data["users"] = [u for u in data.get("users", []) if u.get("id") != user_id]
        await write_json(self._index_path, data)
