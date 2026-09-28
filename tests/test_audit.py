"""审计日志测试。

审计的两条铁律必须被测试锁住：
1. 写审计失败不能影响业务（审计是旁路设施）
2. 敏感信息不得进入 detail（密码、token）
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture()
def audit_env(tmp_path, monkeypatch):
    """把数据库指向临时文件，避免污染真实的 agent.db。"""
    db_path = tmp_path / "audit_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("DB_AUTO_CREATE", "1")

    # 重新导入，让模块按新的 DATABASE_URL 建 engine
    import importlib
    import server.database as database
    import server.audit as audit_module
    importlib.reload(database)
    importlib.reload(audit_module)
    return audit_module, db_path


class TestAuditRecord:
    def test_record_and_query(self, audit_env):
        audit, _ = audit_env
        audit.record(audit.LOGIN, actor="alice", target="-", request_id="rid-1")

        rows = audit.recent(actor="alice")
        assert len(rows) == 1
        assert rows[0]["action"] == audit.LOGIN
        assert rows[0]["actor"] == "alice"
        assert rows[0]["outcome"] == "success"

    def test_failure_outcome_recorded(self, audit_env):
        audit, _ = audit_env
        audit.record(
            audit.LOGIN_FAILED, actor="bob", outcome="failure", detail="密码错误"
        )
        rows = audit.recent(actor="bob")
        assert rows[0]["outcome"] == "failure"

    def test_filter_by_actor(self, audit_env):
        audit, _ = audit_env
        audit.record(audit.LOGIN, actor="alice")
        audit.record(audit.LOGIN, actor="bob")
        assert len(audit.recent(actor="alice")) == 1
        assert len(audit.recent()) == 2  # 管理员视角：全部

    def test_limit_respected(self, audit_env):
        audit, _ = audit_env
        for i in range(5):
            audit.record(audit.LOGIN, actor="alice", detail=f"#{i}")
        assert len(audit.recent(actor="alice", limit=2)) == 2

    def test_newest_first(self, audit_env):
        audit, _ = audit_env
        audit.record(audit.REGISTER, actor="c1")
        audit.record(audit.CHANGE_PASSWORD, actor="c1")
        rows = audit.recent(actor="c1")
        assert rows[0]["action"] == audit.CHANGE_PASSWORD, "最新记录应排在最前"


class TestAuditSafety:
    def test_write_failure_does_not_raise(self, audit_env, monkeypatch):
        """审计写库失败不能让业务操作跟着失败。"""
        audit, _ = audit_env
        monkeypatch.setattr(audit, "SessionLocal", lambda: _BrokenSession())
        # 不应抛出
        audit.record(audit.DELETE_DOCUMENT, actor="alice", target="x.md")

    def test_no_password_in_detail(self, audit_env):
        """detail 里绝不能出现密码等敏感内容。

        这里校验的是"调用约定"：审计内容由调用方决定，
        测试确保我们的 record 不会自己把密码之类的东西塞进去。
        """
        audit, _ = audit_env
        audit.record(
            audit.CHANGE_PASSWORD, actor="alice", detail="旧 token 已全部失效"
        )
        rows = audit.recent(actor="alice")
        # 只检查"内容字段"：动作名本身含 password（change_password），
        # 那是枚举常量不是敏感数据
        for row in rows:
            blob = f"{row['detail']} {row['target']}".lower()
            for secret in ("password=", "token=", "secret=", "sk-"):
                assert secret not in blob


class _BrokenSession:
    """任何操作都失败的会话，用于模拟审计库不可用。"""

    def add(self, *_args, **_kwargs):
        raise RuntimeError("audit db down")

    def commit(self):
        raise RuntimeError("audit db down")

    def rollback(self):
        pass

    def close(self):
        pass

    def query(self, *_args, **_kwargs):
        raise RuntimeError("audit db down")
