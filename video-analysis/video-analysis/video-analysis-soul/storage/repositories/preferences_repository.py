"""用户偏好数据读写"""

from typing import Dict, Optional

from common.config import settings
from common.logger import get_logger
from common.utils.async_utils import read_json, write_json
from common.utils.datetime import now
from storage.models.preferences import UserPreferences

logger = get_logger(__name__)


class PreferencesRepository:
    """用户偏好仓库"""

    def __init__(self):
        self._base_dir = settings.soul_data_dir / "users"

    def _path(self, user_id: str):
        return self._base_dir / user_id / "preferences.json"

    async def get(self, user_id: str) -> UserPreferences:
        """获取用户偏好，不存在则返回空白"""
        path = self._path(user_id)
        if path.exists():
            data = await read_json(path)
            return UserPreferences(**data)
        return UserPreferences(user_id=user_id)

    async def update(self, prefs: UserPreferences) -> UserPreferences:
        """覆写保存"""
        prefs.last_updated = now()
        await write_json(
            self._path(prefs.user_id), prefs.model_dump(mode="json")
        )
        return prefs

    async def merge_from_conversation(
        self, user_id: str, extracted: Dict
    ) -> UserPreferences:
        """合并从对话中提取的偏好"""
        prefs = await self.get(user_id)

        # 合并兴趣（去重）
        new_interests = extracted.get("interests", [])
        if new_interests:
            merged = list(set(prefs.interests + new_interests))
            prefs.interests = merged[-20:]  # 最多保留 20 项

        # 合并近期话题（去重，保留最近 10 个）
        new_topics = extracted.get("recent_topics", [])
        if new_topics:
            merged = list(dict.fromkeys(new_topics + prefs.recent_topics))
            prefs.recent_topics = merged[:10]

        # 覆写单值字段（仅当提取到有效值时）
        for field in ("visit_motivation", "personality_type", "communication_style"):
            val = extracted.get(field)
            if val:
                setattr(prefs, field, val)

        # 合并知识水平
        new_kl = extracted.get("knowledge_level", {})
        if new_kl:
            prefs.knowledge_level.update(new_kl)

        # 更新收集进度
        for key in ("interests", "visit_motivation", "personality_type",
                     "communication_style", "recent_topics"):
            if extracted.get(key):
                prefs.collection_progress[key] = True

        return await self.update(prefs)
