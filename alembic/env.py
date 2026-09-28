"""Alembic 环境配置。

连接串从 DATABASE_URL 环境变量读取（默认 sqlite:///./agent.db），
与 server/database.py 保持一致，避免两处配置漂移。
"""

from logging.config import fileConfig
import os

# 必须在导入 server.database **之前**关掉自动建表：
# 否则 create_all 会先把表建好，紧接着的 alembic upgrade 再建一次就会冲突。
# 迁移期间，schema 的所有权归 Alembic。
os.environ["DB_AUTO_CREATE"] = "0"

from alembic import context
from sqlalchemy import create_engine

from server.database import Base  # noqa: E402,F401  （导入以注册所有模型）


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent.db")

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """生成 SQL 脚本（不连库）。"""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(DATABASE_URL)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
