"""知识检索服务"""

from typing import Dict, List, Optional

from common.config import settings
from common.logger import get_logger
from managers.persona_manager import PersonaManager
from storage.vector_stores.chroma_store import SearchResult

logger = get_logger(__name__)


class RetrievalService:
    """
    知识检索服务

    封装 PersonaManager 的搜索接口，负责:
    - 调用 PersonaManager.search_knowledge（内含 embedding + ChromaDB 检索）
    - 按配置的 rerank_top_k 截取结果
    - 格式化检索结果为 prompt 上下文字符串
    """

    def __init__(self, persona_manager: PersonaManager):
        self._persona_manager = persona_manager

    async def search_knowledge(
        self,
        persona_name: str,
        query: str,
        top_k: Optional[int] = None,
    ) -> List[Dict]:
        """
        搜索博主知识库

        Returns:
            List[Dict] 每项包含 text, distance, metadata, context_before, context_after
        """
        k = top_k or settings.persona.knowledge_retrieval.top_k
        context_window = settings.persona.knowledge_retrieval.context_window

        try:
            results: List[SearchResult] = self._persona_manager.search_knowledge(
                persona_name,
                query,
                n_results=k,
                context_window=context_window if settings.persona.knowledge_retrieval.include_context else 0,
            )

            # 转为 dict 列表
            result_dicts = [r.to_dict() for r in results]

            # rerank 截取
            rerank_k = settings.persona.knowledge_retrieval.rerank_top_k
            if rerank_k and len(result_dicts) > rerank_k:
                result_dicts = result_dicts[:rerank_k]

            logger.info(
                f"Knowledge search: persona={persona_name}, "
                f"query='{query[:50]}', results={len(result_dicts)}"
            )
            return result_dicts

        except Exception as e:
            logger.error(f"Knowledge search failed for {persona_name}: {e}")
            return []

    def format_context(self, results: List[Dict]) -> str:
        """
        格式化检索结果为 prompt 上下文

        格式:
        [1] 前文... | 匹配内容 | 后文... (来源: 视频标题)
        """
        if not results:
            return ""

        parts = []
        for i, r in enumerate(results, 1):
            text = r.get("text", "")
            meta = r.get("metadata", {})
            video = meta.get("video_title", "")
            ctx_before = r.get("context_before", [])
            ctx_after = r.get("context_after", [])

            # 组装带上下文的文本
            segments = []
            if ctx_before:
                segments.append("...".join(ctx_before))
            segments.append(text)
            if ctx_after:
                segments.append("...".join(ctx_after))

            full_text = " ".join(segments)
            source_info = f" (来源: {video})" if video else ""
            distance = r.get("distance", 0)
            relevance = f" [相关度: {1 - distance:.2f}]" if distance else ""

            parts.append(f"[{i}] {full_text}{source_info}{relevance}")

        return "\n\n".join(parts)
