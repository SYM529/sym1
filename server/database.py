import os

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

DATABASE_URL = "sqlite:///./agent.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    # 管理员：评测看板等管理功能只对这类用户开放
    is_admin = Column(Boolean, default=False, nullable=False, server_default="0")
    # 密码版本号：改密时自增，旧 token 因版本号不匹配立即失效。
    # JWT 本身是无状态的，签出去就收不回来——没有版本号的话，
    # 改了密码旧 token 仍能用到过期为止，等于改了个寂寞。
    password_version = Column(Integer, default=0, nullable=False, server_default="0")


Base.metadata.create_all(bind=engine)


def _ensure_columns() -> None:
    """轻量迁移：create_all 不会给**已存在**的表加新列，缺列时手动补。

    只加列不改类型，SQLite 的 ALTER TABLE 足够；启动时执行一次，幂等。
    """
    additions = {
        "is_admin": "BOOLEAN DEFAULT 0",
        "password_version": "INTEGER DEFAULT 0",
    }
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
        for name, definition in additions.items():
            if name not in cols:
                conn.execute(
                    text(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                )


_ensure_columns()


def sync_admin_users() -> None:
    """把 ADMIN_USERS 环境变量里列出的用户名同步为管理员。

    每次启动执行一次：名单里的人提权，从名单里移除的人不会自动降权
    （降权是敏感操作，显式改库比悄悄降级更可预期）。
    """
    names = {n.strip() for n in os.getenv("ADMIN_USERS", "demo").split(",") if n.strip()}
    if not names:
        return
    with engine.begin() as conn:
        for name in names:
            conn.execute(
                text("UPDATE users SET is_admin = 1 WHERE username = :n"),
                {"n": name},
            )


sync_admin_users()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()