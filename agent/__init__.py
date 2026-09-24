"""Agent 包。

在包初始化阶段就加载 .env，这是必须的：

- `agent.rag.config` 等模块把环境变量读成模块级常量，导入时就定型；
- 而 `python -m agent.rag.ingest` 这类入口会**先**执行本文件完成父包初始化，
  然后才执行目标模块里的 `load_dotenv()`——那时配置已经被读成空值了。

父包的初始化一定先于任何子模块，所以在这里加载可以覆盖所有入口。
load_dotenv 是幂等的，其他地方重复调用没有副作用。
"""

from dotenv import load_dotenv

load_dotenv()
