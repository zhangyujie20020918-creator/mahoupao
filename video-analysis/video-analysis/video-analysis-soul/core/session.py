"""会话管理"""

from typing import Dict, Optional

from common.logger import get_logger
from managers.cache_manager import SessionCacheManager, SessionData

logger = get_logger(__name__)


class SessionManager:
    """会话管理器 - 管理用户会话生命周期"""

    def __init__(self, cache_manager: SessionCacheManager):
        self._cache = cache_manager

    async def get_session(self, user_id: str, persona_name: str) -> SessionData:
        """获取或创建会话"""
        return await self._cache.get_or_create(user_id, persona_name)

    async def add_message(
        self, user_id: str, persona_name: str, role: str, content: str
    ) -> None:
        """添加消息到会话缓存"""
        await self._cache.add_message(
            user_id, persona_name, {"role": role, "content": content}
        )

    async def get_cached_messages(
        self, user_id: str, persona_name: str
    ) -> list:
        """获取缓存的消息"""
        return await self._cache.get_messages(user_id, persona_name)

    @property
    def active_sessions(self) -> int:
        """活跃会话数"""
        return self._cache.active_count
