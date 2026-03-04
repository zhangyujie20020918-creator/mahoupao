"""记忆数据读写"""

from pathlib import Path
from typing import Optional

from common.config import settings
from common.logger import get_logger
from common.utils.async_utils import read_json, write_json
from storage.models.memory import LongTermMemory, Preview

logger = get_logger(__name__)


class MemoryRepository:
    """记忆数据仓库"""

    def __init__(self):
        self._base_dir = settings.soul_data_dir / "users"

    def _user_dir(self, user_id: str) -> Path:
        return self._base_dir / user_id

    def _preview_path(self, user_id: str, persona_name: str) -> Path:
        return self._user_dir(user_id) / "conversations" / persona_name / "preview.json"

    def _long_term_path(self, user_id: str) -> Path:
        return self._user_dir(user_id) / "long_term_memory.json"

    async def get_preview(self, user_id: str, persona_name: str) -> Optional[Preview]:
        """获取用户对某 Persona 的记忆总览"""
        path = self._preview_path(user_id, persona_name)
        if not path.exists():
            return None
        data = await read_json(path)
        return Preview(**data)

    async def save_preview(self, preview: Preview, persona_name: str) -> None:
        """保存记忆总览"""
        path = self._preview_path(preview.user_id, persona_name)
        path.parent.mkdir(parents=True, exist_ok=True)
        await write_json(path, preview.model_dump(mode="json"))

    async def get_long_term_memory(self, user_id: str) -> Optional[LongTermMemory]:
        """获取长期记忆"""
        path = self._long_term_path(user_id)
        if not path.exists():
            return None
        data = await read_json(path)
        return LongTermMemory(**data)

    async def save_long_term_memory(self, memory: LongTermMemory) -> None:
        """保存长期记忆"""
        path = self._long_term_path(memory.user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        await write_json(path, memory.model_dump(mode="json"))
