"""条件路由函数"""

from core.graph.state import SoulState


def route_after_analysis(state: SoulState) -> str:
    """分析后的路由决策"""
    from core.graph.nodes.route_decision import route_decision
    return route_decision(state)


def route_after_soul_search(state: SoulState) -> str:
    """搜索后的路由"""
    if state.get("needs_memory_recall"):
        return "search_memory"
    return "generate"


def route_after_memory_search(state: SoulState) -> str:
    """记忆搜索后的路由"""
    if state.get("needs_detailed_history"):
        return "load_history"
    return "generate"
