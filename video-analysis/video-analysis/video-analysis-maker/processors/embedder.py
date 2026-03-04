import logging
from typing import List, Optional
import torch
from sentence_transformers import SentenceTransformer

from config import get_settings

logger = logging.getLogger(__name__)


class TextEmbedder:
    """使用 BGE 模型生成文本 embedding"""

    def __init__(self, model_name: Optional[str] = None):
        self.settings = get_settings()
        self.model_name = model_name or self.settings.embedding_model

        # 检测设备
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

        # 加载模型
        logger.info(f"Loading embedding model: {self.model_name}")
        self.model = SentenceTransformer(self.model_name, device=self.device)
        logger.info("Embedding model loaded successfully")

    def encode(self, texts: List[str], batch_size: int = 32, show_progress: bool = True) -> List[List[float]]:
        """
        将文本列表转换为 embedding 向量

        Args:
            texts: 文本列表
            batch_size: 批处理大小
            show_progress: 是否显示进度条

        Returns:
            embedding 向量列表
        """
        if not texts:
            return []

        # BGE 模型建议对查询添加前缀，但对于文档不需要
        embeddings = self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=show_progress,
            convert_to_numpy=True,
            normalize_embeddings=True  # 归一化，便于计算余弦相似度
        )

        return embeddings.tolist()

    def encode_query(self, query: str) -> List[float]:
        """
        编码查询文本（BGE 模型建议对查询添加前缀）

        Args:
            query: 查询文本

        Returns:
            embedding 向量
        """
        # BGE 模型的查询前缀
        query_with_prefix = f"为这个句子生成表示以用于检索相关文章：{query}"

        embedding = self.model.encode(
            query_with_prefix,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        return embedding.tolist()

    def encode_single(self, text: str) -> List[float]:
        """
        编码单个文本

        Args:
            text: 文本

        Returns:
            embedding 向量
        """
        embedding = self.model.encode(
            text,
            convert_to_numpy=True,
            normalize_embeddings=True
        )

        return embedding.tolist()

    @property
    def embedding_dimension(self) -> int:
        """获取 embedding 维度"""
        return self.model.get_sentence_embedding_dimension()
