import logging
import os

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Boolean, text
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

logger = logging.getLogger(__name__)

# 库地址与 alembic/env.py 一致地读取环境变量：
# 生产/测试可以指向其它库，也避免两处配置漂移
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./agent.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class AuditLog(Base):
    """审计日志：记录"谁在什么时候对什么做了什么"。

    为什么单独建表而不是只打日志：日志是给人看的流水，
    审计需要**可查询、可追溯、不可被应用日志清理策略带走**。
    删除、改密、清空会话这些不可逆操作，事后要能回答"是谁干的"。
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    ts = Column(DateTime, default=datetime.now, index=True)
    actor = Column(String, index=True)          # 操作者用户名
    action = Column(String, index=True)         # login / delete_doc / change_password ...
    target = Column(String)                     # 操作对象（文件名、会话 id 等）
    outcome = Column(String, default="success") # success / failure
    detail = Column(String)                     # 补充说明（禁止写密码等敏感信息）
    request_id = Column(String)                 # 串联同一次请求的日志


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


# 生产环境请用 Alembic 管理 schema（DB_AUTO_CREATE=0）：
#   alembic upgrade head        # 新库
#   alembic stamp 0001          # 已存在的旧库标记为已迁移
# 开发时保留自动建表，省去每次重建库都要跑迁移的麻烦。
if os.getenv("DB_AUTO_CREATE", "1").lower() not in ("0", "off", "false", "no"):
    Base.metadata.create_all(bind=engine)


def _ensure_columns() -> None:
    """给**历史遗留**的旧库补列。

    create_all 不会给已存在的表加新列，所以老库需要这一步。
    全新库由 Alembic 负责，这里遇到"表还不存在"必须安静跳过——
    否则 alembic upgrade head 会在建表之前先被这段启动代码打断。
    """
    additions = {
        "is_admin": "BOOLEAN DEFAULT 0",
        "password_version": "INTEGER DEFAULT 0",
    }
    try:
        with engine.begin() as conn:
            cols = [row[1] for row in conn.execute(text("PRAGMA table_info(users)"))]
            if not cols:  # 表不存在：交给迁移
                return
            for name, definition in additions.items():
                if name not in cols:
                    conn.execute(
                        text(f"ALTER TABLE users ADD COLUMN {name} {definition}")
                    )
    except Exception as e:
        logger.warning("检查用户表结构失败（不影响启动）：%s", e)


def sync_admin_users() -> None:
    """把 ADMIN_USERS 环境变量里列出的用户名同步为管理员。

    每次启动执行一次：名单里的人提权，从名单里移除的人不会自动降权
    （降权是敏感操作，显式改库比悄悄降级更可预期）。
    """
    names = {n.strip() for n in os.getenv("ADMIN_USERS", "demo").split(",") if n.strip()}
    if not names:
        return
    try:
        with engine.begin() as conn:
            for name in names:
                conn.execute(
                    text("UPDATE users SET is_admin = 1 WHERE username = :n"),
                    {"n": name},
                )
    except Exception as e:
        # 表还没建（全新库等迁移）时不要中断启动
        logger.warning("同步管理员名单失败：%s", e)


sync_admin_users()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()