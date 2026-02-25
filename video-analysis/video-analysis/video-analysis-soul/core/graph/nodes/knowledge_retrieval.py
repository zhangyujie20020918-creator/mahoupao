"""知识检索节点"""

from core.graph.state import SoulState
from common.logger import get_logger

logger = get_logger(__name__)


async def knowledge_retrieval(state: SoulState, **deps) -> dict:
    """
    从 ChromaDB 检索相关视频内容

    - 检索 top_k 相关片段
    - 带上下文窗口（前后各 N 段）
    """
    retrieval_service = deps.get("retrieval_service")

    try:
        results = await retrieval_service.search_knowledge(
            persona_name=state["blogger_name"],
            query=state["user_message"],
        )

        # 提取 sources
        sources = []
        for r in results:
            meta = r.get("metadata", {})
            sources.append({
                "video": meta.get("video_title", ""),
                "segment": meta.get("segment_index", 0),
                "text": r.get("text", "")[:200],
                "relevance": 1 - r.get("distance", 0),
            })

        logger.info(f"Knowledge retrieval: found {len(results)} results")

        return {
            "blogger_context": results,
            "sources": sources,
        }

    except Exception as e:
        logger.error(f"Knowledge retrieval failed: {e}")
        return {
            "blogger_context": [],
            "sources": [],
        }
