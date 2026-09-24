"""多 Agent 图的状态定义。

与单 ReAct 循环的区别：这里把"中间产物"显式放进 state，
而不是全塞进 messages。好处是每个专家只读写自己关心的字段，
互不干扰，也便于单独观察某一路的结果。
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

# 路由选项
ROUTE_KNOWLEDGE = "knowledge"   # 查本地知识库
ROUTE_SEARCH = "search"         # 联网搜索实时信息
ROUTE_COMPUTE = "compute"       # 精确数值计算
ROUTE_TIME = "time"             # 当前时间/日期
ROUTE_DIRECT = "direct"         # 无需工具，直接回答

ALL_ROUTES = [
    ROUTE_KNOWLEDGE,
    ROUTE_SEARCH,
    ROUTE_COMPUTE,
    ROUTE_TIME,
    ROUTE_DIRECT,
]


class AgentState(TypedDict, total=False):
    messages: Annotated[list[Any], add_messages]
    question: str
    routes: list[str]
    route_reason: str
    knowledge_context: str       # 知识库检索到的带编号上下文
    citations: list[dict]        # 引用来源，供前端展示
    search_result: str           # 联网搜索结果
    compute_result: str          # 计算工具结果
    time_result: str             # 当前时间
    errors: list[str]            # 各专家的失败信息，不中断主流程
