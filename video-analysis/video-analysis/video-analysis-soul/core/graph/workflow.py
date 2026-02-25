"""LangGraph 工作流构建"""

from functools import partial
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from common.logger import get_logger
from core.graph.nodes.analyze_message import analyze_message
from core.graph.nodes.connection_rewrite import connection_rewrite
from core.graph.nodes.extract_preferences import extract_preferences
from core.graph.nodes.generate_response import generate_response
from core.graph.nodes.greeting_flow import greeting_flow
from core.graph.nodes.knowledge_retrieval import knowledge_retrieval
from core.graph.nodes.load_context import load_context
from core.graph.nodes.load_detail_history import load_detail_history
from core.graph.nodes.memory_retrieval import memory_retrieval
from core.graph.nodes.post_process import post_process
from core.graph.nodes.update_memory import update_memory
from core.graph.routes import (
    route_after_analysis,
    route_after_soul_search,
    route_after_memory_search,
)
from core.graph.state import SoulState

logger = get_logger(__name__)


def build_workflow(deps: Dict[str, Any]) -> StateGraph:
    """
    构建 LangGraph 工作流

    Args:
        deps: 依赖注入字典，包含各 manager 和 service 实例
    """
    # 创建带依赖的节点函数
    def _wrap(fn):
        async def wrapped(state):
            return await fn(state, **deps)
        return wrapped

    # 创建 Graph
    workflow = StateGraph(SoulState)

    # 添加节点
    workflow.add_node("load_context", _wrap(load_context))
    workflow.add_node("analyze_intent", _wrap(analyze_message))
    workflow.add_node("greeting", _wrap(greeting_flow))
    workflow.add_node("search_soul", _wrap(knowledge_retrieval))
    workflow.add_node("search_memory", _wrap(memory_retrieval))
    workflow.add_node("load_history", _wrap(load_detail_history))
    workflow.add_node("generate", _wrap(generate_response))
    workflow.add_node("connection_rewrite", _wrap(connection_rewrite))
    workflow.add_node("post_process", _wrap(post_process))
    workflow.add_node("extract_preferences", _wrap(extract_preferences))
    workflow.add_node("update_memory", _wrap(update_memory))

    # 设置入口
    workflow.set_entry_point("load_context")

    # load_context → analyze_intent
    workflow.add_edge("load_context", "analyze_intent")

    # 条件路由: analyze_intent → greeting | search_soul | search_memory | both | direct
    workflow.add_conditional_edges(
        "analyze_intent",
        route_after_analysis,
        {
            "greeting": "greeting",
            "soul_search": "search_soul",
            "memory_search": "search_memory",
            "both": "search_soul",  # 先搜，再搜记忆
            "direct": "generate",
        },
    )

    # greeting → connection_rewrite
    workflow.add_edge("greeting", "connection_rewrite")

    # 搜索后的路由
    workflow.add_conditional_edges(
        "search_soul",
        route_after_soul_search,
        {
            "search_memory": "search_memory",
            "generate": "generate",
        },
    )

    # 记忆搜索后的路由
    workflow.add_conditional_edges(
        "search_memory",
        route_after_memory_search,
        {
            "load_history": "load_history",
            "generate": "generate",
        },
    )

    # 详细历史 → 生成
    workflow.add_edge("load_history", "generate")

    # 生成 → 连接改写 → 后处理 → 偏好提取 → 更新记忆 → 结束
    workflow.add_edge("generate", "connection_rewrite")
    workflow.add_edge("connection_rewrite", "post_process")
    workflow.add_edge("post_process", "extract_preferences")
    workflow.add_edge("extract_preferences", "update_memory")
    workflow.add_edge("update_memory", END)

    logger.info("LangGraph workflow built successfully")
    return workflow
