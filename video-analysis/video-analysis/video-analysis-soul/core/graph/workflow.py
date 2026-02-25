"""LangGraph 工作流构建"""

from functools import partial
from typing import Any, Dict

from langgraph.graph import END, StateGraph

from common.logger import get_logger
from core.graph.nodes.analyze_message import analyze_message
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
    route_after_blogger_search,
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
    workflow.add_node("search_blogger", _wrap(knowledge_retrieval))
    workflow.add_node("search_memory", _wrap(memory_retrieval))
    workflow.add_node("load_history", _wrap(load_detail_history))
    workflow.add_node("generate", _wrap(generate_response))
    workflow.add_node("post_process", _wrap(post_process))
    workflow.add_node("update_memory", _wrap(update_memory))

    # 设置入口
    workflow.set_entry_point("load_context")

    # load_context → analyze_intent
    workflow.add_edge("load_context", "analyze_intent")

    # 条件路由: analyze_intent → greeting | search_blogger | search_memory | both | direct
    workflow.add_conditional_edges(
        "analyze_intent",
        route_after_analysis,
        {
            "greeting": "greeting",
            "blogger_search": "search_blogger",
            "memory_search": "search_memory",
            "both": "search_blogger",  # 先搜博主，再搜记忆
            "direct": "generate",
        },
    )

    # greeting → post_process
    workflow.add_edge("greeting", "post_process")

    # 博主搜索后的路由
    workflow.add_conditional_edges(
        "search_blogger",
        route_after_blogger_search,
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

    # 生成 → 后处理 → 更新记忆 → 结束
    workflow.add_edge("generate", "post_process")
    workflow.add_edge("post_process", "update_memory")
    workflow.add_edge("update_memory", END)

    logger.info("LangGraph workflow built successfully")
    return workflow
