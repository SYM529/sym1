"""MCP Server：把项目里的工具暴露成标准 MCP 服务。

为什么值得做这件事
------------------
改造之前，这 4 个工具是以 LangChain `@tool` 的形式存在的，
只有本项目内的 Agent 能用。换一个框架、换一个 Agent、或者想让
Claude Desktop / Cursor 之类的客户端直接调用，就得重写一遍。

MCP（Model Context Protocol）把"工具怎么被调用"标准化了：
本模块是**薄适配层**，不含任何业务逻辑，只做协议转换——
真正的实现仍然复用 `agent.tools` 与 `agent.rag.tool`，
因此工具的修复（比如 AST 白名单求值、range 内存炸弹拦截）
一次改动、多处受益。

为什么是薄适配层而不是重新实现
------------------------------
曾经考虑过在 MCP 里重新写一遍 calculate，那样调用链更短，
但代价是安全逻辑出现两份实现、两份测试，任何一边漏改都会
留下不一致的漏洞。这里选择复用 `.invoke()`，
把"一处实现、多处接入"落到实处。

运行方式
--------
    python -m agent.mcp_server                    # stdio（默认）
    MCP_TRANSPORT=streamable-http python -m agent.mcp_server
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

def _server_class():
    """拿到 Server 类，兼容 MCP SDK v1 / v2。

    v2 把 `FastMCP` 改名为 `MCPServer` 并换了包路径，直接用 `mcp.server.fastmcp`
    在装到 2.x 时会 ImportError。两者对外用到的 API（`@tool()`、`run(transport=)`、
    `list_tools()`）是一致的，所以这里按版本取别名即可，不必锁死在旧大版本。
    """
    try:
        from mcp.server.mcpserver import MCPServer  # mcp >= 2.0

        return MCPServer
    except ImportError:
        try:
            from mcp.server.fastmcp import FastMCP  # mcp < 2.0

            return FastMCP
        except ImportError as e:
            raise SystemExit(
                "未安装 mcp 依赖，请先执行：pip install -r requirements.txt"
            ) from e


_Server = _server_class()

SERVER_NAME = os.getenv("MCP_SERVER_NAME", "agent-tools")
# stdio 用于 Claude Desktop / Cursor 这类本地客户端；
# streamable-http 用于远程部署，可多客户端共享一个服务实例
TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio")

server = _Server(SERVER_NAME)


def _rag_enabled() -> bool:
    """判断知识库是否可用。

    与 `agent.service._rag_available` 保持同一套判断规则：
    空库挂载只会让每次检索都返回"没有找到"，徒增一轮调用。
    """
    flag = os.getenv("RAG_ENABLED", "auto").lower()
    if flag in ("0", "off", "false", "no"):
        return False
    if flag in ("1", "on", "true", "yes"):
        return True
    try:
        from agent.rag import is_ready

        return is_ready()
    except Exception as e:
        logger.debug("知识库不可用：%s", e)
        return False


@server.tool()
def calculate(expression: str) -> str:
    """执行精确的数学计算。

    基于 AST 白名单求值，不使用 eval，因此可以安全地接受外部输入。
    支持四则运算、括号、**（幂）、常用函数（sqrt/log/sin/cos/abs/round/min/max/factorial）、
    常量 pi 与 e，以及 sum(range(a, b)) 形式的求和。

    参数：
        expression: 数学表达式，例如 "123 * 456"、"sqrt(2) + pi"、"sum(range(1, 101))"
    """
    # 延迟导入：让服务在没有 Tavily / 向量库的环境下也能只启动需要的部分
    from agent.tools import calculate as _calculate

    return _calculate.invoke({"expression": expression})


@server.tool()
def get_current_time() -> str:
    """获取当前本地时间，返回格式 YYYY-MM-DD HH:MM:SS。

    适用于"现在几点""今天几号"这类问题。
    不要用它推断天气、新闻等实时信息——那些需要联网搜索。
    """
    from agent.tools import get_current_time as _now

    return _now.invoke({})


@server.tool()
def web_search(query: str) -> str:
    """联网搜索实时信息，返回 Top3 结果的标题与摘要。

    适用于天气、新闻、股价、赛事、当前事件等依赖外部实时数据的问题。
    """
    from agent.tools import web_search as _search

    return _search.invoke({"query": query})


def _register_rag_tool() -> bool:
    """知识库可用时注册检索工具，返回是否注册成功。

    放在函数里而不是用顶层 if，是为了让 MCP 客户端拉取工具列表时
    就能看到"当前有没有知识库"，而不是调用后才发现用不了。
    """
    if not _rag_enabled():
        return False

    @server.tool()
    def search_knowledge_base(query: str) -> str:
        """检索本地知识库，返回带编号引用的原始资料片段。

        适用于文档、内部资料、项目配置类问题。
        不适用于天气、新闻等实时信息（应使用 web_search）。
        """
        from agent.rag.tool import search_knowledge_base as _kb

        return _kb.invoke({"query": query})

    return True


# 在模块导入时完成注册：MCP 客户端连上来就要能拿到完整的工具列表
rag_registered = _register_rag_tool()


def main() -> None:
    logger.info(
        "MCP Server 启动：name=%s transport=%s knowledge_base=%s",
        SERVER_NAME, TRANSPORT, rag_registered,
    )
    server.run(transport=TRANSPORT)


if __name__ == "__main__":
    main()
