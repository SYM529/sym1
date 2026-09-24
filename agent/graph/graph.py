"""构建多 Agent 图。

流程：

    START → classify ──┬─→ knowledge ─┐
                       ├─→ search ────┼→ synthesize → END
                       ├─→ compute ───┘
                       └─→ (direct) ──┘

classify 之后的分支由 LangGraph 并行执行——这是本架构相对单 ReAct 循环
最实际的两点收益：

1. **并行**：知识库检索与联网搜索同时进行，而不是串行等待
2. **分流**：每个专家只拿到自己需要的上下文，避免 4 个工具的 schema
   和 6 条规则同时挤在一个 prompt 里互相干扰
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from agent.graph.nodes import (
    classify,
    compute_expert,
    knowledge_expert,
    route_targets,
    search_expert,
    synthesize,
    time_expert,
)
from agent.graph.state import (
    ROUTE_COMPUTE,
    ROUTE_KNOWLEDGE,
    ROUTE_SEARCH,
    ROUTE_TIME,
    AgentState,
)

EXPERT_NODES = {
    ROUTE_KNOWLEDGE: knowledge_expert,
    ROUTE_SEARCH: search_expert,
    ROUTE_COMPUTE: compute_expert,
    ROUTE_TIME: time_expert,
}


def build_graph():
    """编译多 Agent 图。"""
    graph = StateGraph(AgentState)

    graph.add_node("classify", classify)
    for name, node in EXPERT_NODES.items():
        graph.add_node(name, node)
    graph.add_node("synthesize", synthesize)

    graph.add_edge(START, "classify")
    # 返回节点名列表即可触发并行分支
    graph.add_conditional_edges("classify", route_targets)
    for name in EXPERT_NODES:
        graph.add_edge(name, "synthesize")
    graph.add_edge("synthesize", END)

    return graph.compile()
