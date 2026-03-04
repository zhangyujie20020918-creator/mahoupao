"""FAISS 向量存储封装（用户记忆语义搜索）"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from common.logger import get_logger

logger = get_logger(__name__)


class FAISSStore:
    """FAISS 向量存储 - 用于用户记忆的语义搜索"""

    def __init__(self):
        self._indices: Dict[str, object] = {}

    async def build_index(self, user_id: str, texts: List[str]) -> None:
        """为用户构建 FAISS 索引"""
        # TODO: 集成 sentence-transformers + FAISS
        logger.info(f"Building FAISS index for user {user_id} with {len(texts)} texts")

    async def search(
        self, user_id: str, query: str, top_k: int = 5
    ) -> List[Tuple[str, float]]:
        """语义搜索用户记忆"""
        # TODO: 实现 FAISS 搜索
        return []

    def close(self, user_id: Optional[str] = None) -> None:
        """关闭索引"""
        if user_id:
            self._indices.pop(user_id, None)
        else:
            self._indices.clear()
