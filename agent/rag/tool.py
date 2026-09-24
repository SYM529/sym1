"""把知识库检索包装成 Agent 工具。

工具描述会影响模型"什么时候调用它"，所以要写清楚适用与不适用场景，
否则模型要么过度调用、要么根本不用。
"""

from __future__ import annotations

import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# 最近一次检索产生的引用，供服务层读取后随 SSE 下发给前端展示。
# 局限：这是模块级状态，高并发下可能串扰；生产环境应改为请求级隔离
# （例如用 contextvars 配合 LangGraph 的 run_id）。
_last_citations: list[dict] = []


def take_citations() -> list[dict]:
    """取出并清空最近一次检索的引用，避免跨请求残留。"""
    global _last_citations
    citations = _last_citations
    _last_citations = []
    return citations


ANSWER_INSTRUCTION = (
    "请基于以上资料回答，并在相关句子末尾用 [编号] 标注引用来源。"
    "只使用资料中明确包含的信息；若资料不足以回答，直接说明知识库中没有，"
    "不要补充你自己的推测。"
)


@tool
def search_knowledge_base(query: str) -> str:
    """检索本地知识库，获取与问题相关的原始资料片段。

    适用于：用户问题涉及项目文档、产品说明、内部资料、上传过的文件内容等
    可能存在于知识库中的信息。

    不适用于：天气、新闻、股价等实时信息（应使用联网搜索）。

    输入应为能表达检索意图的关键词或完整问题。
    """
    try:
        from agent.rag import get_retriever

        retriever = get_retriever()
        result = retriever.retrieve(query)
    except Exception as e:
        # 工具失败不能让整个 Agent 崩掉，返回可读错误让模型自行降级
        logger.warning("知识库检索失败：%s", e)
        return f"知识库检索失败：{type(e).__name__}。可以改用联网搜索，或如实告知用户。"

    if not result.hit:
        take_citations()      # 清空上一次的残留引用
        return (
            "知识库中没有检索到相关资料。请不要编造内容："
            "可以如实告知用户知识库里没有，或改用联网搜索获取公开信息。"
        )

    global _last_citations
    _last_citations = [
        {
            "index": c.index,
            "source": c.source,
            "heading": c.heading,
            "score": c.score,
            "text": c.text,
        }
        for c in result.citations
    ]

    citations = "\n".join(
        f"[{c.index}] {c.source}" + (f" · {c.heading}" if c.heading else "")
        for c in result.citations
    )
    return (
        f"检索到 {len(result.citations)} 条相关资料：\n\n"
        f"{result.context}\n\n"
        f"引用来源对照：\n{citations}\n\n"
        f"{ANSWER_INSTRUCTION}"
    )
