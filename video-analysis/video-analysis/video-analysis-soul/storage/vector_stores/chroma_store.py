"""ChromaDB 向量存储封装 - 兼容 maker 的数据格式"""

import gc
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import chromadb
from chromadb.config import Settings as ChromaSettings

from common.logger import get_logger
from common.utils.text import get_collection_name

logger = get_logger(__name__)


@dataclass
class SearchResult:
    """搜索结果（与 maker 的 SearchResult 对齐）"""

    text: str
    video_title: str
    segment_index: int
    start: float
    end: float
    distance: float
    context_before: List[str]
    context_after: List[str]

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "distance": self.distance,
            "metadata": {
                "video_title": self.video_title,
                "segment_index": self.segment_index,
                "start": self.start,
                "end": self.end,
            },
            "context_before": self.context_before,
            "context_after": self.context_after,
        }


class ChromaStore:
    """
    ChromaDB 向量存储

    直接连接 maker 生成的 chroma_db 目录，只读检索。
    查询时必须使用与 maker 相同的 BGE embedding 模型。
    """

    def __init__(self):
        self._clients: Dict[str, chromadb.PersistentClient] = {}
        self._collections: Dict[str, chromadb.Collection] = {}

    def connect(self, persona_name: str, db_path: str) -> chromadb.Collection:
        """连接到 Persona 的 ChromaDB（只读）"""
        if persona_name in self._collections:
            return self._collections[persona_name]

        client = chromadb.PersistentClient(
            path=db_path,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._clients[persona_name] = client

        collection_name = get_collection_name(persona_name)
        collection = client.get_collection(
            name=collection_name,
        )
        self._collections[persona_name] = collection

        logger.info(
            f"Connected to ChromaDB: persona={persona_name}, "
            f"collection={collection_name}"
        )
        return collection

    def search(
        self,
        persona_name: str,
        query_embedding: List[float],
        n_results: int = 5,
        context_window: int = 2,
    ) -> List[SearchResult]:
        """
        使用 embedding 向量搜索相关内容

        Args:
            persona_name: Persona 名称
            query_embedding: 查询向量（由 EmbeddingService.encode_query 生成）
            n_results: 返回结果数量
            context_window: 上下文窗口大小（前后各取几段）
        """
        if persona_name not in self._collections:
            raise ValueError(f"Collection not connected: {persona_name}")

        collection = self._collections[persona_name]

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        search_results = []
        if not results["documents"] or not results["documents"][0]:
            return search_results

        for i, (doc, meta, dist) in enumerate(
            zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            )
        ):
            # 获取上下文
            ctx_before, ctx_after = self._get_context(
                collection,
                meta.get("video_title", ""),
                meta.get("segment_index", 0),
                meta.get("total_segments", 1),
                context_window,
            )

            search_results.append(
                SearchResult(
                    text=doc,
                    video_title=meta.get("video_title", ""),
                    segment_index=meta.get("segment_index", 0),
                    start=meta.get("start", 0.0),
                    end=meta.get("end", 0.0),
                    distance=dist,
                    context_before=ctx_before,
                    context_after=ctx_after,
                )
            )

        return search_results

    def _get_context(
        self,
        collection: chromadb.Collection,
        video_title: str,
        segment_index: int,
        total_segments: int,
        context_window: int,
    ) -> tuple[List[str], List[str]]:
        """
        获取段落的上下文（前后各 N 段）

        ID 格式与 maker 一致: "{video_title}_{segment_index}"
        """
        context_before = []
        context_after = []

        if context_window <= 0:
            return context_before, context_after

        # 前面的段落
        for i in range(max(0, segment_index - context_window), segment_index):
            doc_id = f"{video_title}_{i}"
            try:
                result = collection.get(ids=[doc_id], include=["documents"])
                if result["documents"]:
                    context_before.append(result["documents"][0])
            except Exception:
                pass

        # 后面的段落
        for i in range(
            segment_index + 1,
            min(total_segments, segment_index + context_window + 1),
        ):
            doc_id = f"{video_title}_{i}"
            try:
                result = collection.get(ids=[doc_id], include=["documents"])
                if result["documents"]:
                    context_after.append(result["documents"][0])
            except Exception:
                pass

        return context_before, context_after

    def get_stats(self, persona_name: str) -> Dict:
        """获取集合统计信息"""
        if persona_name not in self._collections:
            return {"connected": False}

        collection = self._collections[persona_name]
        try:
            count = collection.count()
        except Exception:
            count = -1  # 索引损坏
        return {
            "connected": True,
            "collection_name": collection.name,
            "document_count": count,
        }

    # ---- 重建索引 ----

    def rebuild_from_optimized_texts(
        self,
        persona_name: str,
        db_path: str,
        optimized_texts_dir: str,
        encode_fn,
    ) -> int:
        """
        从 maker 的 optimized_texts/ 目录重建 ChromaDB

        当 HNSW 索引损坏时调用。读取所有 optimized_texts/*.json，
        用 BGE 模型重新编码，写入全新的 ChromaDB。

        重建策略（避免 Windows 文件锁）:
        1. 优先: 复用已有 client，delete_collection + 重建
        2. 回退: 关闭旧连接 + gc + 删除目录 + 全新 client

        Args:
            persona_name: Persona 名称
            db_path: ChromaDB 路径
            optimized_texts_dir: optimized_texts 目录路径
            encode_fn: embedding 编码函数 (texts: List[str]) -> List[List[float]]

        Returns:
            写入的文档数量
        """
        texts_dir = Path(optimized_texts_dir)
        if not texts_dir.exists():
            raise FileNotFoundError(f"optimized_texts not found: {texts_dir}")

        # 收集所有文本和元数据
        all_texts, all_metadatas, all_ids = self._collect_from_optimized_texts(
            texts_dir, persona_name
        )

        if not all_texts:
            logger.warning(f"No texts found in {texts_dir}")
            return 0

        logger.info(
            f"Rebuilding ChromaDB for {persona_name}: {len(all_texts)} segments from {texts_dir}"
        )

        collection_name = get_collection_name(persona_name)

        # 策略1: 复用已有 client，删除旧 collection 后重建（避免文件锁）
        client = self._clients.get(persona_name)
        if client is not None:
            try:
                client.delete_collection(name=collection_name)
                logger.info(f"Deleted corrupt collection: {collection_name}")
            except Exception as e:
                logger.warning(f"delete_collection failed: {e}, trying full rebuild")
                client = None

        # 策略2: 关闭旧连接，删除目录，新建 client
        if client is None:
            self.close(persona_name)
            gc.collect()  # 释放 Rust/C++ 文件句柄

            db_dir = Path(db_path)
            if db_dir.exists():
                try:
                    shutil.rmtree(db_dir)
                except PermissionError:
                    logger.warning(
                        f"Cannot delete {db_dir} (file locked), "
                        f"trying alternative path"
                    )
                    # 用备用路径
                    db_path = str(db_dir) + "_rebuilt"
                    db_dir = Path(db_path)
                    if db_dir.exists():
                        shutil.rmtree(db_dir)

            db_dir.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(
                path=str(db_dir),
                settings=ChromaSettings(anonymized_telemetry=False),
            )

        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"soul": persona_name, "hnsw:space": "cosine"},
        )

        # 批量编码和写入
        batch_size = 64
        total_added = 0

        for i in range(0, len(all_texts), batch_size):
            batch_texts = all_texts[i : i + batch_size]
            batch_metas = all_metadatas[i : i + batch_size]
            batch_ids = all_ids[i : i + batch_size]

            embeddings = encode_fn(batch_texts)

            collection.add(
                ids=batch_ids,
                embeddings=embeddings,
                documents=batch_texts,
                metadatas=batch_metas,
            )
            total_added += len(batch_texts)
            logger.info(f"  Added {total_added}/{len(all_texts)} documents...")

        # 缓存新连接
        self._clients[persona_name] = client
        self._collections[persona_name] = collection

        logger.info(
            f"ChromaDB rebuilt: persona={persona_name}, "
            f"collection={collection_name}, docs={total_added}"
        )
        return total_added

    def _collect_from_optimized_texts(
        self, texts_dir: Path, persona_name: str
    ) -> Tuple[List[str], List[Dict], List[str]]:
        """
        从 optimized_texts 目录收集所有文本、元数据、ID

        文件格式（与 maker 一致）:
        {
            "video_title": "...",
            "soul_name": "...",
            "segments": [
                {"optimized_text": "...", "segment_index": 0, "start": 0.0, "end": 5.0},
                ...
            ]
        }
        """
        all_texts = []
        all_metadatas = []
        all_ids = []

        for json_file in sorted(texts_dir.glob("*.json")):
            try:
                with open(json_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read {json_file}: {e}")
                continue

            video_title = data.get("video_title", json_file.stem)
            segments = data.get("segments", [])

            if segments:
                for seg in segments:
                    text = seg.get("optimized_text", "")
                    if not text:
                        continue

                    seg_idx = int(seg.get("segment_index", 0))
                    doc_id = f"{video_title}_{seg_idx}"

                    all_ids.append(doc_id)
                    all_texts.append(text)
                    all_metadatas.append({
                        "video_title": video_title,
                        "soul_name": persona_name,
                        "segment_index": seg_idx,
                        "start": float(seg.get("start", 0.0)),
                        "end": float(seg.get("end", 0.0)),
                        "total_segments": len(segments),
                    })
            else:
                # 无分段，用 optimized_full_text
                text = data.get("optimized_full_text", "")
                if not text:
                    continue
                doc_id = f"{video_title}_0"
                all_ids.append(doc_id)
                all_texts.append(text)
                all_metadatas.append({
                    "video_title": video_title,
                    "soul_name": persona_name,
                    "segment_index": 0,
                    "start": 0.0,
                    "end": 0.0,
                    "total_segments": 1,
                })

        return all_texts, all_metadatas, all_ids

    def close(self, persona_name: Optional[str] = None) -> None:
        """关闭连接"""
        if persona_name:
            self._collections.pop(persona_name, None)
            self._clients.pop(persona_name, None)
        else:
            self._collections.clear()
            self._clients.clear()
