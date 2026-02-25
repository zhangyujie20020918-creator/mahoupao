"""动态会话缓存管理器"""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from common.config import CacheConfig, settings
from common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SessionData:
    """会话数据"""

    user_id: str
    persona_name: str
    last_active: datetime = field(default_factory=datetime.now)
    messages: List[Dict] = field(default_factory=list)
    preview_cache: Optional[Dict] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionCacheManager:
    """动态会话缓存管理器"""

    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or settings.cache
        self._sessions: Dict[str, SessionData] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """启动后台清理任务"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session cache manager started")

    async def stop(self) -> None:
        """停止后台清理任务"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        logger.info("Session cache manager stopped")

    def _session_key(self, user_id: str, persona_name: str) -> str:
        return f"{user_id}:{persona_name}"

    async def get_or_create(self, user_id: str, persona_name: str) -> SessionData:
        """获取或创建会话"""
        key = self._session_key(user_id, persona_name)

        async with self._lock:
            if key in self._sessions:
                session = self._sessions[key]
                session.last_active = datetime.now()
                return session

            # 检查是否超过最大会话数
            if len(self._sessions) >= self.config.max_sessions:
                await self._evict_oldest()

            session = SessionData(user_id=user_id, persona_name=persona_name)
            self._sessions[key] = session
            return session

    async def update(self, user_id: str, persona_name: str, **kwargs) -> None:
        """更新会话数据"""
        key = self._session_key(user_id, persona_name)
        async with self._lock:
            if key in self._sessions:
                session = self._sessions[key]
                session.last_active = datetime.now()
                for k, v in kwargs.items():
                    if hasattr(session, k):
                        setattr(session, k, v)

    async def add_message(self, user_id: str, persona_name: str, message: Dict) -> None:
        """追加消息到缓存"""
        session = await self.get_or_create(user_id, persona_name)
        async with self._lock:
            session.messages.append(message)
            # 限制消息数量
            if len(session.messages) > self.config.max_messages_per_session:
                session.messages = session.messages[-self.config.max_messages_per_session:]

    async def get_messages(self, user_id: str, persona_name: str) -> List[Dict]:
        """获取缓存的消息"""
        key = self._session_key(user_id, persona_name)
        async with self._lock:
            if key in self._sessions:
                return list(self._sessions[key].messages)
        return []

    async def _cleanup_loop(self) -> None:
        """定期清理过期会话"""
        while True:
            await asyncio.sleep(self.config.cleanup_interval_seconds)
            await self._cleanup_idle_sessions()

    async def _cleanup_idle_sessions(self) -> None:
        """清理空闲会话"""
        current = datetime.now()
        async with self._lock:
            expired = [
                sid
                for sid, session in self._sessions.items()
                if (current - session.last_active).total_seconds()
                > self.config.idle_timeout_seconds
            ]
            for sid in expired:
                del self._sessions[sid]
                logger.info(f"Released idle session: {sid}")

    async def _evict_oldest(self) -> None:
        """淘汰最久未活跃的会话"""
        if not self._sessions:
            return
        oldest_key = min(
            self._sessions, key=lambda k: self._sessions[k].last_active
        )
        del self._sessions[oldest_key]
        logger.info(f"Evicted oldest session: {oldest_key}")

    @property
    def active_count(self) -> int:
        return len(self._sessions)
