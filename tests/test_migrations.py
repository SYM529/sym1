"""数据库迁移测试。

Alembic 迁移是"生产能不能安全升级"的关键：
- 新库必须能靠迁移从零建出完整 schema（不能只依赖代码里的 create_all）
- 建出来的字段要和 ORM 模型一致，否则运行时会报 no such column
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# ORM 模型期望的列（与 server/database.py 的 User 对齐）
EXPECTED_COLUMNS = {
    "id", "username", "hashed_password", "created_at",
    "is_admin", "password_version",
}


def _run_alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, DATABASE_URL=db_url)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_upgrade_creates_full_schema():
    alembic_available = True
    try:
        import alembic  # noqa: F401
    except ImportError:
        alembic_available = False
    if not alembic_available:
        pytest.skip("alembic 未安装")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "migrated.db"
        result = _run_alembic(f"sqlite:///{db_path}", "upgrade", "head")
        assert result.returncode == 0, f"迁移失败：{result.stderr}"
        assert db_path.exists(), "迁移后数据库文件应存在"

        conn = sqlite3.connect(db_path)
        try:
            cols = {
                row[1]
                for row in conn.execute("PRAGMA table_info(users)")
            }
        finally:
            conn.close()

        missing = EXPECTED_COLUMNS - cols
        assert not missing, f"迁移缺少字段：{missing}"


def test_downgrade_drops_table():
    try:
        import alembic  # noqa: F401
    except ImportError:
        pytest.skip("alembic 未安装")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "rollback.db"
        assert _run_alembic(f"sqlite:///{db_path}", "upgrade", "head").returncode == 0
        down = _run_alembic(f"sqlite:///{db_path}", "downgrade", "base")
        assert down.returncode == 0, f"回滚失败：{down.stderr}"

        conn = sqlite3.connect(db_path)
        try:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        finally:
            conn.close()
        assert "users" not in tables, "回滚后 users 表应被删除"
