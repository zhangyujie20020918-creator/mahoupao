"""路由决策节点"""

from core.graph.state import SoulState


def route_decision(state: SoulState) -> str:
    """
    根据意图决定走哪个检索分支

    返回: "greeting" | "soul_search" | "memory_search" | "both" | "direct"
    """
    intent = state.get("intent", "chat")

    # 打招呼走独立流程
    if intent == "greeting" and not state.get("today_messages"):
        return "greeting"

    needs_knowledge = state.get("needs_soul_knowledge", False)
    needs_memory = state.get("needs_memory_recall", False)

    if needs_knowledge and needs_memory:
        return "both"
    elif needs_knowledge:
        return "soul_search"
    elif needs_memory:
        return "memory_search"
    else:
        return "direct"
