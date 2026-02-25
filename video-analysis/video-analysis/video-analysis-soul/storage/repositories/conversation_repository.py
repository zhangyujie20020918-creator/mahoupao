"""对话数据读写"""

from pathlib import Path
from typing import List, Optional

from common.config import settings
from common.logger import get_logger
from common.utils.async_utils import read_json, write_json
from common.utils.datetime import today_str
from storage.models.message import DailyConversation, Message

logger = get_logger(__name__)


class ConversationRepository:
    """对话数据仓库"""

    def __init__(self):
        self._base_dir = settings.soul_data_dir / "users"

    def _conv_dir(self, user_id: str, persona_name: str) -> Path:
        return self._base_dir / user_id / "conversations" / persona_name

    def _conv_path(self, user_id: str, persona_name: str, date: str) -> Path:
        return self._conv_dir(user_id, persona_name) / f"{date}.json"

    async def get_today(
        self, user_id: str, persona_name: str
    ) -> DailyConversation:
        """获取今日对话（不存在则创建空对话）"""
        date = today_str()
        path = self._conv_path(user_id, persona_name, date)

        if path.exists():
            data = await read_json(path)
            return DailyConversation(**data)

        return DailyConversation(
            date=date,
            user_id=user_id,
            soul=persona_name,
        )

    async def get_by_date(
        self, user_id: str, persona_name: str, date: str
    ) -> Optional[DailyConversation]:
        """获取指定日期的对话"""
        path = self._conv_path(user_id, persona_name, date)
        if not path.exists():
            return None
        data = await read_json(path)
        return DailyConversation(**data)

    async def save(self, conversation: DailyConversation) -> None:
        """保存对话"""
        path = self._conv_path(
            conversation.user_id,
            conversation.soul,
            conversation.date,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        conversation.message_count = len(conversation.messages)
        await write_json(path, conversation.model_dump(mode="json"))

    async def add_message(
        self, user_id: str, persona_name: str, message: Message
    ) -> DailyConversation:
        """追加消息到今日对话"""
        conv = await self.get_today(user_id, persona_name)
        conv.messages.append(message)
        conv.message_count = len(conv.messages)
        await self.save(conv)
        return conv

    async def list_dates(self, user_id: str, persona_name: str) -> List[str]:
        """列出所有有对话的日期"""
        conv_dir = self._conv_dir(user_id, persona_name)
        if not conv_dir.exists():
            return []

        dates = []
        for f in sorted(conv_dir.glob("*.json")):
            if f.stem != "preview":
                dates.append(f.stem)
        return dates

    async def get_recent_messages(
        self, user_id: str, persona_name: str, limit: int = 20
    ) -> List[Message]:
        """获取最近的消息"""
        conv = await self.get_today(user_id, persona_name)
        return conv.messages[-limit:]
