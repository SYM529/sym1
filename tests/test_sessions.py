"""会话索引与历史回放测试。

两条必须锁死的逻辑：

1. **标题只在会话创建时生成。** 之后换话题也不改名——
   "这个会话是聊什么的"需要锚点，会话名漂移会让侧边栏失去意义。
2. **死条目必须清理。** 会话本体有 TTL，索引没有；
   不清理的话侧边栏越用越假：列表还在，点进去全是空会话。
"""

from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage,
)

from server import sessions


class FakePipeline:
    """收集命令、execute 时统一回放，语义与真实 pipeline 一致。

    直接执行 + 空返回值的做法是错的：list_sessions 依赖 execute()
    把每个 EXISTS 的结果按顺序带回来。
    """

    def __init__(self, client):
        self._client = client
        self._commands: list[tuple] = []

    def _queue(self, name, *args):
        self._commands.append((name, args))
        return self

    def hset(self, key, field, value):
        return self._queue("hset", key, field, value)

    def expire(self, key, ttl):
        return self._queue("expire", key, ttl)

    def exists(self, key):
        return self._queue("exists", key)

    def execute(self):
        results = [getattr(self._client, name)(*args) for name, args in self._commands]
        self._commands = []
        return results


class FakeRedis:
    """最小可用的 Redis 替身：哈希 + 存在性检查。"""

    def __init__(self):
        self.hashes: dict[str, dict] = {}
        self.keys: set[str] = set()

    def pipeline(self):
        return FakePipeline(self)

    def expire(self, key, ttl):
        return True

    def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    def hget(self, key, field):
        return self.hashes.get(key, {}).get(field)

    def hgetall(self, key):
        return self.hashes.get(key, {})

    def hdel(self, key, *fields):
        bucket = self.hashes.get(key, {})
        for field in fields:
            bucket.pop(field, None)

    def exists(self, key):
        return 1 if key in self.keys else 0


class BrokenRedis:
    def __getattr__(self, name):
        raise RuntimeError("redis is down")


def alive(r, user_id, session_id):
    """让索引条目对应的会话本体"存在"。"""
    r.keys.add(f"session:{user_id}:{session_id}")


class TestTitle:
    def test_truncates_long_message(self):
        # 25 个字：必须超过 TITLE_MAX_CHARS(24) 才会触发截断
        title = sessions.session_title("帮我详细解释一下微服务架构的优缺点以及它们适用什么场景")
        assert title.endswith("…")
        assert len(title) <= sessions.TITLE_MAX_CHARS + 1

    def test_collapses_whitespace(self):
        assert sessions.session_title("  你好\n  世界  ") == "你好 世界"

    def test_empty_message_falls_back(self):
        assert sessions.session_title("") == "新对话"
        assert sessions.session_title(None) == "新对话"


class TestIndexLifecycle:
    def test_record_then_list(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "帮我算一下 123 乘以 456", 3600)
        alive(r, 1, "s1")

        result = sessions.list_sessions(r, 1)

        assert len(result) == 1
        assert result[0]["session_id"] == "s1"
        assert result[0]["title"] == "帮我算一下 123 乘以 456"
        assert result[0]["updated_at"]

    def test_title_does_not_drift_on_re_record(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "聊聊无人机", 3600)
        sessions.record_session(r, 1, "s1", "帮我算一下 1 加 1", 3600)
        alive(r, 1, "s1")

        result = sessions.list_sessions(r, 1)

        # 换了话题也不改名：会话名需要锚点
        assert result[0]["title"] == "聊聊无人机"
        assert result[0]["updated_at"]  # 但活跃时间要刷新

    def test_users_are_isolated(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "用户一的问题", 3600)
        alive(r, 1, "s1")

        assert sessions.list_sessions(r, 2) == []

    def test_expired_sessions_are_pruned_from_index(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "dead", "这条已经过期", 3600)
        sessions.record_session(r, 1, "live", "这条还活着", 3600)
        alive(r, 1, "live")   # 只有 live 的会话本体还在

        result = sessions.list_sessions(r, 1)

        assert [s["session_id"] for s in result] == ["live"]
        # 死条目要被顺手删掉，而不是每次列表都带着它
        assert sessions.list_sessions(r, 1) == result

    def test_removing_from_index(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "问题", 3600)
        alive(r, 1, "s1")

        sessions.remove_session(r, 1, "s1")

        assert sessions.list_sessions(r, 1) == []


class TestRename:
    def test_renames_display_title(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "帮我算一下 123 乘以 456", 3600)
        alive(r, 1, "s1")

        assert sessions.rename_session(r, 1, "s1", "乘法演示") is True
        assert sessions.list_sessions(r, 1)[0]["title"] == "乘法演示"

    def test_rename_trims_and_caps_length(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "原标题", 3600)
        alive(r, 1, "s1")

        sessions.rename_session(r, 1, "s1", "  " + "长" * 80 + "  ")

        title = sessions.list_sessions(r, 1)[0]["title"]
        assert title == "长" * 60

    def test_rename_missing_session_returns_false(self):
        # 从未聊过的会话不该被"重命名成功"：明确 False，接口层回 404
        r = FakeRedis()
        assert sessions.rename_session(r, 1, "ghost", "新名字") is False

    def test_rename_does_not_touch_messages_or_other_users(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "s1", "用户一的问题", 3600)
        sessions.record_session(r, 2, "s1", "用户二的问题", 3600)
        alive(r, 1, "s1")
        alive(r, 2, "s1")

        sessions.rename_session(r, 1, "s1", "只改我的")

        titles = {s["session_id"]: s["title"] for s in
                  sessions.list_sessions(r, 1) + sessions.list_sessions(r, 2)}
        # 用户二的同名会话不能被误伤
        assert titles["s1"] in ("只改我的", "用户二的问题")
        assert sessions.list_sessions(r, 2)[0]["title"] == "用户二的问题"

    def test_sorted_by_recent_activity(self):
        r = FakeRedis()
        sessions.record_session(r, 1, "old", "早的问题", 3600)
        alive(r, 1, "old")
        sessions.record_session(r, 1, "new", "晚的问题", 3600)
        alive(r, 1, "new")

        result = sessions.list_sessions(r, 1)

        # updated_at 取自登记时间，后登记的排前面
        assert result[0]["session_id"] == "new"

    def test_redis_failure_returns_empty_list(self):
        assert sessions.list_sessions(BrokenRedis(), 1) == []

    def test_recording_failure_is_swallowed(self):
        sessions.record_session(BrokenRedis(), 1, "s1", "问题", 3600)


class TestReadableMessages:
    def test_keeps_only_human_and_final_ai(self):
        messages = [
            HumanMessage(content="帮我算一下 23 乘以 47"),
            AIMessage(content="", tool_calls=[
                {"name": "calculate", "args": {"expression": "23*47"}, "id": "c1"},
            ]),
            ToolMessage(content="1081", tool_call_id="c1", name="calculate"),
            AIMessage(content="23 × 47 = 1081"),
            SystemMessage(content="【此前对话摘要】……"),
        ]

        items = sessions.readable_messages(messages)

        assert items == [
            {"type": "human", "content": "帮我算一下 23 乘以 47"},
            {"type": "ai", "content": "23 × 47 = 1081"},
        ]

    def test_attachment_marker_is_stripped(self):
        messages = [
            HumanMessage(content="这是什么\n[用户附带了一张图片，file_id=u1/x.png]"),
        ]

        items = sessions.readable_messages(messages)

        assert items[0]["content"] == "这是什么"

    def test_empty_ai_messages_are_dropped(self):
        # 空内容的 AI 消息通常是中间态，回放时没有意义
        messages = [AIMessage(content=""), HumanMessage(content="在吗")]

        assert sessions.readable_messages(messages) == [
            {"type": "human", "content": "在吗"}
        ]
