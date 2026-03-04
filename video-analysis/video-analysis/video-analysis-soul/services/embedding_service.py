"""Embedding 服务 - 使用与 maker 相同的 BGE 模型"""

from typing import List, Optional

import torch
from sentence_transformers import SentenceTransformer

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

# BGE 查询前缀（与 maker 的 embedder.py 一致）
BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


class EmbeddingService:
    """
    Embedding 服务

    使用与 video-analysis-maker 完全相同的 BGE 模型和参数，
    确保查询向量与存储向量在同一空间中。
    """

    # 模型名称（与 maker config 一致）
    MODEL_NAME = "BAAI/bge-large-zh-v1.5"

    def __init__(self):
        self._model: Optional[SentenceTransformer] = None
        self._device: str = ""

    @property
    def is_initialized(self) -> bool:
        return self._model is not None

    def initialize(self) -> None:
        """
        同步初始化 embedding 模型

        启动时调用一次，后续所有 encode 操作都复用这个模型实例。
        """
        if self._model is not None:
            return

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Loading embedding model: {self.MODEL_NAME} (device: {self._device})")

        self._model = SentenceTransformer(self.MODEL_NAME, device=self._device)

        logger.info(
            f"Embedding model loaded: dim={self._model.get_sentence_embedding_dimension()}"
        )

    def encode(self, texts: List[str]) -> List[List[float]]:
        """编码文本列表为向量（用于文档 embedding）"""
        if not self._model:
            raise RuntimeError("EmbeddingService not initialized, call initialize() first")
        if not texts:
            return []

        embeddings = self._model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def encode_query(self, query: str) -> List[float]:
        """
        编码查询文本（BGE 模型需要对查询添加特殊前缀）

        与 maker 的 TextEmbedder.encode_query() 完全一致。
        """
        if not self._model:
            raise RuntimeError("EmbeddingService not initialized, call initialize() first")

        query_with_prefix = f"{BGE_QUERY_PREFIX}{query}"

        embedding = self._model.encode(
            query_with_prefix,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return embedding.tolist()

    @property
    def embedding_dimension(self) -> int:
        """获取 embedding 维度"""
        if not self._model:
            return 0
        return self._model.get_sentence_embedding_dimension()
