"""长上下文管理：把早期对话压缩成摘要。

改造前的做法与它的问题
----------------------
此前 `server.main` 只做窗口裁剪（`_trim_history` 保留最后 20 条）。
这能保证不超长，但被裁掉的内容是**彻底消失**的：

- 第 3 轮说"我叫小明，回答用中文"，到第 25 轮模型已经不知道了；
- 前面试算过的关键数值被丢掉，用户问"再加 350"时算错。

摘要保留了这些语义，代价是细节丢失——这是上下文预算与信息保真之间
的取舍，没有两全的做法。本模块的策略是：

    近期 KEEP_RECENT 条原样保留（细节优先）
    +  更早的部分压成一条 system 摘要（语义优先）

两条不可忽视的边界
------------------
1. **工具调用不能拆散。** 带 tool_calls 的 AI 消息必须和它的 ToolMessage
   在一起，否则模型会收到"调用了工具但没有结果"的残缺序列。
   这里按"工具调用组"整体处理。
2. **摘要失败必须能退化。** 多一次 LLM 调用，就多一个失败点。
   摘要失败时不重试魔法，而是退回原来的窗口裁剪——
   宁可丢旧的，也不要让会话写不回去。
"""

from __future__ import annotations

import asyncio
import logging
import os

from langchain_core.messages import HumanMessage, SystemMessage

logger = logging.getLogger(__name__)

# 超过这个消息数就触发压缩。取值要低于 main.MAX_HISTORY(20)：
# 否则历史会先被裁剪到 20 条，永远够不到触发线，压缩一次都不会发生。
COMPRESS_TRIGGER = int(os.getenv("COMPRESS_TRIGGER", "16"))
# 长文本场景兜底：消息条数不多但已经很长时也压缩
COMPRESS_MAX_CHARS = int(os.getenv("COMPRESS_MAX_CHARS", "6000"))
# 原样保留的最近消息数
KEEP_RECENT = int(os.getenv("COMPRESS_KEEP_RECENT", "8"))
# 摘要是额外的 LLM 调用，超时就放弃，不能拖住整条请求
COMPRESS_TIMEOUT = float(os.getenv("COMPRESS_TIMEOUT", "10"))

SUMMARY_PREFIX = "【此前对话摘要】"

SUMMARIZE_SYSTEM = """你是对话摘要生成器。把下面的历史对话压缩成一段紧凑的中文摘要。

必须保留：
1. 用户的身份信息与明确偏好（例如"回答用中文""不要输出表格"）
2. 已经确立的事实、决策，以及出现过的**关键数值**
3. 尚未完成、下一轮还可能接着聊的问题或待办

可以省略：
- 寒暄、重复确认、已经完成的中间过程
- 工具的原始返回报文（保留结论即可）

严格要求：
- 用第三人称陈述句书写，不要还原成对话形式。
- 不要新增、推断或补全任何原文没有的信息。
- 控制在 300 字以内。"""


def estimate_chars(messages) -> int:
    """粗略估算消息占用量。

    用字符数而不是精确 token 数：精确的 tokenizer 要额外引入依赖，
    而对"要不要压缩"这种粗粒度判断，字符数已经足够，
    且对中英文混合语料比按词切分更稳定。
    """
    return sum(len(m.content or "") for m in messages)


def needs_compression(messages) -> tuple[bool, str]:
    """判断是否需要压缩，并返回触发原因（便于日志排查）。"""
    if not messages:
        return False, ""
    if len(messages) > COMPRESS_TRIGGER:
        return True, f"消息数 {len(messages)} > {COMPRESS_TRIGGER}"
    chars = estimate_chars(messages)
    if chars > COMPRESS_MAX_CHARS:
        return True, f"字符数 {chars} > {COMPRESS_MAX_CHARS}"
    return False, ""


def _tool_call_groups(messages) -> list[list]:
    """把消息切成不可分割的组。

    带 tool_calls 的 AI 消息与紧跟其后的所有 ToolMessage 是一组，
    压缩时作为一个整体决定去留。
    """
    groups: list[list] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            group = [msg]
            i += 1
            while i < n and messages[i].type == "tool":
                group.append(messages[i])
                i += 1
            groups.append(group)
        else:
            groups.append([msg])
            i += 1
    return groups


def split_for_compression(messages, keep_recent: int = KEEP_RECENT) -> tuple[list, list]:
    """把消息切成 (待压缩的旧消息, 原样保留的新消息)。

    从尾部整组地取，取满 keep_recent 条为止——保证不会把一个
    工具调用组劈成两半。
    """
    if not messages:
        return [], []

    groups = _tool_call_groups(messages)
    kept: list[list] = []
    kept_count = 0

    for group in reversed(groups):
        if kept and kept_count >= keep_recent:
            break
        kept.insert(0, group)
        kept_count += len(group)

    old_groups = groups[: len(groups) - len(kept)]
    old = [m for g in old_groups for m in g]
    recent = [m for g in kept for m in g]
    return old, recent


def _render_for_summary(messages) -> str:
    """把消息渲染成给摘要看的文本。工具返回体截断，避免噪声塞满上下文。"""
    lines = []
    for m in messages:
        content = (m.content or "").strip()
        if not content:
            continue
        if m.type in ("human", "user"):
            prefix = "用户"
        elif m.type == "ai":
            prefix = "助手"
        elif m.type == "tool":
            prefix = f"工具({getattr(m, 'name', '') or 'unknown'})"
        elif is_summary_message(m):
            # 滚动摘要：上一轮的摘要会被喂给下一轮，标注清楚来源
            # 能避免模型把它当成用户刚开始说的话。
            prefix = "此前摘要"
        else:
            prefix = "系统"
        lines.append(f"{prefix}：{content[:500]}")
    return "\n".join(lines)


async def _default_summarize(messages) -> str:
    """调用模型生成摘要。延迟 import，避免模块加载时就要求 API Key。"""
    from agent.llm import get_model

    response = await get_model().ainvoke([
        SystemMessage(content=SUMMARIZE_SYSTEM),
        HumanMessage(content=_render_for_summary(messages)),
    ])
    return (response.content or "").strip()


async def compress_history(messages, summarize=None, timeout: float = COMPRESS_TIMEOUT):
    """压缩历史，返回新消息列表。

    summarize 可注入，便于单元测试用一个假的摘要函数替换真实模型。
    """
    summarize = summarize or _default_summarize
    old, recent = split_for_compression(messages)
    if not old:
        return messages, False

    try:
        summary = await asyncio.wait_for(summarize(old), timeout=timeout)
    except Exception as e:
        # 超时或模型出错都不重试：直接退回原文，宁可不压缩也不能丢会话
        logger.warning("对话摘要失败，本次不压缩：%s", e)
        return messages, False

    # 模型偶尔会只吐空白或换行。必须 strip 后再判：
    # 否则一条空摘要会被当成有效内容存进上下文，占着预算却不提供任何信息。
    summary = (summary or "").strip()
    if not summary:
        return messages, False

    logger.info(
        "对话已压缩：%d 条 -> 1 条摘要 + %d 条近期消息", len(messages), len(recent)
    )
    return [SystemMessage(content=f"{SUMMARY_PREFIX}\n{summary}"), *recent], True


async def maybe_compress(messages, summarize=None):
    """满足条件才压缩。这是给服务层用的入口。"""
    needed, reason = needs_compression(messages)
    if not needed:
        return messages, False
    logger.info("触发对话压缩：%s", reason)
    return await compress_history(messages, summarize=summarize)


def is_summary_message(message) -> bool:
    """判断一条消息是不是摘要。用于避免把摘要本身再喂给摘要模型重复压。"""
    return (message.content or "").startswith(SUMMARY_PREFIX)
