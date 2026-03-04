"""记忆管理器"""

import gzip
import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from common.config import settings
from common.logger import get_logger
from common.utils.async_utils import read_json, write_json
from common.utils.datetime import now, today_str
from storage.models.memory import (
    LongTermFact,
    LongTermMemory,
    MemoryEntry,
    MemorySummary,
    Preview,
)
from storage.models.message import DailyConversation, Message
from storage.repositories.conversation_repository import ConversationRepository
from storage.repositories.memory_repository import MemoryRepository

logger = get_logger(__name__)


class MemoryManager:
    """记忆管理"""

    def __init__(self):
        self._memory_repo = MemoryRepository()
        self._conv_repo = ConversationRepository()

    # ---- Preview 操作 ----

    async def get_preview(self, user_id: str, persona_name: str) -> Preview:
        """获取记忆总览"""
        preview = await self._memory_repo.get_preview(user_id, persona_name)
        if not preview:
            preview = Preview(user_id=user_id)
        return preview

    async def update_preview(
        self, user_id: str, persona_name: str, summary: MemorySummary
    ) -> Preview:
        """更新记忆总览"""
        preview = await self.get_preview(user_id, persona_name)

        # 更新或添加今日记忆
        today = today_str()
        existing_entry = next(
            (m for m in preview.memories if m.date == today and m.soul == persona_name),
            None,
        )
        if existing_entry:
            existing_entry.summary = summary
        else:
            preview.memories.append(
                MemoryEntry(date=today, soul=persona_name, summary=summary)
            )

        preview.last_updated = now()
        preview.summary_version += 1

        await self._memory_repo.save_preview(preview, persona_name)
        return preview

    # ---- 对话操作 ----

    async def get_today_conversation(
        self, user_id: str, persona_name: str
    ) -> DailyConversation:
        """获取今日对话"""
        return await self._conv_repo.get_today(user_id, persona_name)

    async def add_message(
        self, user_id: str, persona_name: str, message: Message
    ) -> DailyConversation:
        """追加消息"""
        return await self._conv_repo.add_message(user_id, persona_name, message)

    async def get_conversation_by_date(
        self, user_id: str, persona_name: str, date: str
    ) -> Optional[DailyConversation]:
        """获取指定日期对话"""
        return await self._conv_repo.get_by_date(user_id, persona_name, date)

    async def get_conversation_dates(
        self, user_id: str, persona_name: str
    ) -> List[str]:
        """获取对话日期列表"""
        return await self._conv_repo.list_dates(user_id, persona_name)

    # ---- 长期记忆 ----

    async def get_long_term_memory(self, user_id: str) -> LongTermMemory:
        """获取长期记忆"""
        memory = await self._memory_repo.get_long_term_memory(user_id)
        if not memory:
            memory = LongTermMemory(user_id=user_id)
        return memory

    async def add_long_term_fact(self, user_id: str, fact: str, source: str = "") -> None:
        """添加长期记忆事实"""
        memory = await self.get_long_term_memory(user_id)

        # 检查重复
        if any(f.fact == fact for f in memory.facts):
            return

        # 限制数量
        max_facts = settings.memory.long_term.max_facts
        if len(memory.facts) >= max_facts:
            memory.facts = memory.facts[-(max_facts - 1):]

        memory.facts.append(LongTermFact(fact=fact, source=source))
        memory.last_updated = now()

        await self._memory_repo.save_long_term_memory(memory)

    # ---- 记忆搜索 ----

    async def search_memory(
        self, user_id: str, persona_name: str, keywords: List[str]
    ) -> List[MemoryEntry]:
        """在 Preview 中搜索相关记忆"""
        preview = await self.get_preview(user_id, persona_name)
        if not preview.memories:
            return []

        matched = []
        for entry in preview.memories:
            score = self._calculate_relevance(entry, keywords)
            if score > 0:
                matched.append((score, entry))

        matched.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in matched[:5]]

    def _calculate_relevance(self, entry: MemoryEntry, keywords: List[str]) -> float:
        """计算记忆条目与关键词的相关度"""
        score = 0.0
        summary = entry.summary

        # 在各字段中搜索关键词
        searchable_text = " ".join(
            summary.topics_discussed
            + summary.places
            + summary.emotions
            + summary.user_preferences
            + summary.key_facts
            + [p.name for p in summary.people_mentioned]
            + [e.what for e in summary.events]
        )

        for keyword in keywords:
            if keyword in searchable_text:
                score += 1.0

        return score

    # ---- 归档 ----

    async def archive_expired_conversations(self, user_id: str) -> int:
        """归档超过14天的对话，返回归档数量"""
        retention_days = settings.memory.detailed_history.retention_days
        cutoff_date = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
        archived_count = 0

        base_dir = settings.soul_data_dir / "users" / user_id / "conversations"
        if not base_dir.exists():
            return 0

        for persona_dir in base_dir.iterdir():
            if not persona_dir.is_dir():
                continue
            for conv_file in persona_dir.glob("*.json"):
                if conv_file.stem == "preview":
                    continue
                if conv_file.stem < cutoff_date:
                    await self._archive_to_monthly(conv_file, user_id, persona_dir.name)
                    conv_file.unlink()
                    archived_count += 1

        if archived_count > 0:
            logger.info(f"Archived {archived_count} conversations for user {user_id}")

        return archived_count

    async def _archive_to_monthly(
        self, conv_file: Path, user_id: str, persona_name: str
    ) -> None:
        """压缩归档到月度文件"""
        archive_dir = (
            settings.soul_data_dir / "users" / user_id / "archive" / persona_name
        )
        archive_dir.mkdir(parents=True, exist_ok=True)

        year_month = conv_file.stem[:7]  # 2026-02
        archive_file = archive_dir / f"{year_month}.json.gz"

        # 读取对话内容
        data = await read_json(conv_file)

        # 追加到压缩文件
        existing = []
        if archive_file.exists():
            with gzip.open(archive_file, "rt", encoding="utf-8") as f:
                existing = json.loads(f.read())

        existing.append(data)

        with gzip.open(archive_file, "wt", encoding="utf-8") as f:
            f.write(json.dumps(existing, ensure_ascii=False))
