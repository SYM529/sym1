"""多 Agent 编排。

与 `agent.service` 里的单 ReAct 循环是**两套可切换的架构**，
用环境变量 `AGENT_ARCH` 选择（react / graph），便于对比实验。
"""

from agent.graph.graph import build_graph
from agent.graph.state import AgentState

__all__ = ["AgentState", "build_graph"]
