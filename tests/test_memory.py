"""长上下文压缩测试。

最重要的是一条约束：**带 tool_calls 的 AI 消息不能和它的工具结果分开。**
一旦被劈成两半，模型收到的就是"承诺要调用工具、却没有结果"的残缺序列，
行为会变得很不稳定，而且这类问题在线上很难复现定位。

另外两条：
- 触发条件必须真的能够被触发。阈值若高于 main.MAX_HISTORY(20)，
  历史会先被裁剪到 20 条，永远够不到触发线，压缩一次都不会发生。
- 摘要是一次额外的 LLM 调用，失败时必须退回原文，
  绝不能让"压缩失败"演变成"会话写不回去"。
"""

import asyncio

from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)

from server.memory import (
    KEEP_RECENT, SUMMARY_PREFIX, compress_history, is_summary_message,
    maybe_compress, needs_compression, split_for_compression,
)


def run(coro):
    return asyncio.run(coro)


def tool_messages():
    """构造一对不可分离的工具调用消息。"""
    ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "calculate",
            "args": {"expression": "23 * 47"},
            "id": "call_1",
        }],
    )
    tool = ToolMessage(content="1081", tool_call_id="call_1", name="calculate")
    return ai, tool


def simple(count: int, prefix: str = "m"):
    return [HumanMessage(content=f"{prefix}{i}") for i in range(count)]


class TestTrigger:
    def test_short_history_not_triggered(self):
        assert needs_compression(simple(5))[0] is False

    def test_empty_history_not_triggered(self):
        assert needs_compression([])[0] is False

    def test_triggered_by_message_count(self):
        needed, reason = needs_compression(simple(30))

        assert needed is True
        assert "消息数" in reason

    def test_triggered_by_char_length(self):
        # 单条超长消息：条数很少，但已经很占上下文
        needed, reason = needs_compression([HumanMessage(content="长" * 10_000)])

        assert needed is True
        assert "字符数" in reason


class TestSplit:
    def test_keeps_recent_untouched(self):
        messages = simple(20)

        old, recent = split_for_compression(messages)

        assert len(recent) == KEEP_RECENT
        assert recent[-1].content == "m19"
        assert old[0].content == "m0"
        # 一条都不能丢
        assert len(old) + len(recent) == len(messages)

    def test_tool_group_stays_in_recent_when_it_is_recent(self):
        ai, tool = tool_messages()
        messages = simple(13) + [ai, tool] + simple(2, "r")

        old, recent = split_for_compression(messages)

        ai_in_recent = any(m is ai for m in recent)
        tool_in_recent = any(m is tool for m in recent)
        assert ai_in_recent == tool_in_recent, "工具调用与其结果被拆散了"
        assert len(old) + len(recent) == len(messages)

    def test_tool_group_stays_in_old_when_it_is_old(self):
        ai, tool = tool_messages()
        messages = simple(2) + [ai, tool] + simple(18, "k")

        old, recent = split_for_compression(messages)

        ai_in_recent = any(m is ai for m in recent)
        tool_in_recent = any(m is tool for m in recent)
        assert ai_in_recent == tool_in_recent, "工具调用与其结果被拆散了"
        assert ai_in_recent is False
        assert len(old) + len(recent) == len(messages)

    def test_empty_input(self):
        assert split_for_compression([]) == ([], [])


class TestCompress:
    def test_replaces_old_with_system_summary(self):
        async def summarize(messages):
            return "用户叫小明，要求全程用中文回答。"

        messages = simple(20)
        result, compressed = run(compress_history(messages, summarize=summarize))

        assert compressed is True
        assert isinstance(result[0], SystemMessage)
        assert result[0].content.startswith(SUMMARY_PREFIX)
        assert "小明" in result[0].content
        assert len(result) == 1 + KEEP_RECENT
        assert is_summary_message(result[0]) is True

    def test_falls_back_when_summarize_raises(self):
        async def summarize(messages):
            raise RuntimeError("model timeout")

        messages = simple(20)
        result, compressed = run(compress_history(messages, summarize=summarize))

        assert compressed is False
        assert result == messages, "摘要失败必须原样返回，不能丢会话"

    def test_falls_back_when_summary_is_empty(self):
        async def summarize(messages):
            return "   "

        messages = simple(20)
        result, compressed = run(compress_history(messages, summarize=summarize))

        assert compressed is False
        assert result == messages

    def test_maybe_compress_skips_short_history(self):
        calls = {"n": 0}

        async def summarize(messages):
            calls["n"] += 1
            return "摘要"

        messages = simple(3)
        result, compressed = run(maybe_compress(messages, summarize=summarize))

        assert compressed is False
        assert calls["n"] == 0
        assert result is messages

    def test_maybe_compress_works_when_triggered(self):
        async def summarize(messages):
            return "用户偏好用中文。"

        result, compressed = run(maybe_compress(simple(30), summarize=summarize))

        assert compressed is True
        assert len(result) < 30
