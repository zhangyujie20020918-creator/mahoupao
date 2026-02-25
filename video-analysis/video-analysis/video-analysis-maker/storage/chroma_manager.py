import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import get_settings
from processors.embedder import TextEmbedder
from processors.text_optimizer import OptimizedVideo

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """搜索结果"""
    text: str
    video_title: str
    segment_index: int
    start: float
    end: float
    distance: float
    context_before: List[str]  # 前面的段落
    context_after: List[str]   # 后面的段落


class ChromaManager:
    """ChromaDB 向量数据库管理器"""

    def __init__(self, soul_name: str, persist_dir: Optional[Path] = None):
        self.settings = get_settings()
        self.soul_name = soul_name

        # 设置持久化目录
        if persist_dir is None:
            persist_dir = self.settings.get_soul_output_dir(soul_name) / "chroma_db"
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 ChromaDB
        self.client = chromadb.PersistentClient(
            path=str(self.persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False)
        )

        # Collection 名称（移除特殊字符）
        self.collection_name = self._sanitize_collection_name(soul_name)

        # 获取或创建 collection
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"soul": soul_name, "hnsw:space": "cosine"}
        )

        # 初始化 embedder
        self.embedder = TextEmbedder()

        logger.info(f"ChromaManager initialized for {soul_name}, collection: {self.collection_name}")

    def _sanitize_collection_name(self, name: str) -> str:
        """清理 collection 名称，移除不合法字符"""
        # ChromaDB 的 collection 名称要求：3-512字符，只允许 [a-zA-Z0-9._-]
        # 开头和结尾必须是 [a-zA-Z0-9]
        import re
        import hashlib

        # 使用 hash 生成唯一标识（处理中文名称）
        name_hash = hashlib.md5(name.encode('utf-8')).hexdigest()[:8]

        # 只保留字母数字和允许的字符
        sanitized = re.sub(r'[^a-zA-Z0-9._-]', '', name)

        # 如果没有有效字符，使用 soul_ 前缀 + hash
        if not sanitized:
            sanitized = f"soul_{name_hash}"
        else:
            # 确保开头是字母或数字
            if not sanitized[0].isalnum():
                sanitized = f"b{sanitized}"
            # 确保结尾是字母或数字
            if not sanitized[-1].isalnum():
                sanitized = f"{sanitized}0"
            # 添加 hash 确保唯一性
            sanitized = f"{sanitized}_{name_hash}"

        # 确保长度合适 (3-512)
        if len(sanitized) < 3:
            sanitized = f"col_{sanitized}"
        elif len(sanitized) > 512:
            sanitized = sanitized[:512]

        return sanitized

    def add_videos(self, videos: List[OptimizedVideo]):
        """
        将优化后的视频文本添加到向量数据库

        Args:
            videos: 优化后的视频列表
        """
        all_texts = []
        all_metadatas = []
        all_ids = []

        for video in videos:
            if video.segments:
                # 有分段的情况
                for seg in video.segments:
                    doc_id = f"{video.video_title}_{seg.segment_index}"
                    all_ids.append(doc_id)
                    all_texts.append(seg.optimized_text)
                    all_metadatas.append({
                        "video_title": video.video_title,
                        "soul_name": video.soul_name,
                        "segment_index": seg.segment_index,
                        "start": seg.start,
                        "end": seg.end,
                        "total_segments": len(video.segments)
                    })
            else:
                # 无分段，整体作为一个文档
                doc_id = f"{video.video_title}_0"
                all_ids.append(doc_id)
                all_texts.append(video.optimized_full_text)
                all_metadatas.append({
                    "video_title": video.video_title,
                    "soul_name": video.soul_name,
                    "segment_index": 0,
                    "start": 0.0,
                    "end": 0.0,
                    "total_segments": 1
                })

        if not all_texts:
            logger.warning("No texts to add to ChromaDB")
            return

        # 生成 embeddings
        logger.info(f"Generating embeddings for {len(all_texts)} segments...")
        embeddings = self.embedder.encode(all_texts)

        # 批量添加到 ChromaDB
        logger.info(f"Adding {len(all_texts)} documents to ChromaDB...")
        self.collection.add(
            ids=all_ids,
            embeddings=embeddings,
            documents=all_texts,
            metadatas=all_metadatas
        )

        logger.info(f"Successfully added {len(all_texts)} documents to collection {self.collection_name}")

    def search(
        self,
        query: str,
        n_results: int = 5,
        include_context: bool = True
    ) -> List[SearchResult]:
        """
        搜索相关内容

        Args:
            query: 查询文本
            n_results: 返回结果数量
            include_context: 是否包含上下文

        Returns:
            搜索结果列表
        """
        # 编码查询
        query_embedding = self.embedder.encode_query(query)

        # 搜索
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"]
        )

        search_results = []

        if not results["documents"] or not results["documents"][0]:
            return search_results

        for i, (doc, meta, dist) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0]
        )):
            context_before = []
            context_after = []

            if include_context:
                context_before, context_after = self._get_context(
                    meta["video_title"],
                    meta["segment_index"],
                    meta.get("total_segments", 1)
                )

            search_results.append(SearchResult(
                text=doc,
                video_title=meta["video_title"],
                segment_index=meta["segment_index"],
                start=meta["start"],
                end=meta["end"],
                distance=dist,
                context_before=context_before,
                context_after=context_after
            ))

        return search_results

    def _get_context(
        self,
        video_title: str,
        segment_index: int,
        total_segments: int
    ) -> tuple[List[str], List[str]]:
        """获取段落的上下文"""
        context_window = self.settings.context_window
        context_before = []
        context_after = []

        # 获取前面的段落
        for i in range(max(0, segment_index - context_window), segment_index):
            doc_id = f"{video_title}_{i}"
            try:
                result = self.collection.get(ids=[doc_id], include=["documents"])
                if result["documents"]:
                    context_before.append(result["documents"][0])
            except Exception:
                pass

        # 获取后面的段落
        for i in range(segment_index + 1, min(total_segments, segment_index + context_window + 1)):
            doc_id = f"{video_title}_{i}"
            try:
                result = self.collection.get(ids=[doc_id], include=["documents"])
                if result["documents"]:
                    context_after.append(result["documents"][0])
            except Exception:
                pass

        return context_before, context_after

    def get_all_texts(self) -> List[Dict[str, Any]]:
        """获取所有文本及其元数据"""
        results = self.collection.get(include=["documents", "metadatas"])

        texts = []
        for doc, meta in zip(results["documents"], results["metadatas"]):
            texts.append({
                "text": doc,
                "metadata": meta
            })

        return texts

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        count = self.collection.count()
        return {
            "collection_name": self.collection_name,
            "soul_name": self.soul_name,
            "document_count": count,
            "persist_dir": str(self.persist_dir)
        }
