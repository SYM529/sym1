"""审计日志。

覆盖的是**不可逆或敏感**的操作：登录、注册、改密、删除文档、清空会话。
普通读操作不入审计——否则审计表会被噪声淹没，真正要看的时候反而找不到。

两条铁律：
1. **审计失败绝不能影响业务**：写库失败只记 warning，业务照常返回。
   审计是旁路设施，不能因为审计挂了导致用户删不掉文档。
2. **绝不记录敏感内容**：密码、token、密钥一律不写 detail，
   只写"结果是什么"（成功/失败、影响几段），不写"内容是什么"。
"""

from __future__ import annotations

import logging
from datetime import datetime

from server.database import AuditLog, SessionLocal

logger = logging.getLogger(__name__)

# 动作常量：集中定义，避免各处拼写不一致导致查询漏数据
LOGIN = "login"
LOGIN_FAILED = "login_failed"
REGISTER = "register"
CHANGE_PASSWORD = "change_password"
DELETE_DOCUMENT = "delete_document"
CLEAR_SESSION = "clear_session"
CLEAR_ALL_SESSIONS = "clear_all_sessions"
UPLOAD = "upload"


def record(
    action: str,
    actor: str = "",
    target: str = "",
    outcome: str = "success",
    detail: str = "",
    request_id: str = "",
) -> None:
    """写入一条审计记录。

    同时输出一条结构化日志（`event=audit`），
    这样日志系统里也能检索到，不必只依赖数据库。
    """
    entry = {
        "ts": datetime.now(),
        "actor": actor or "-",
        "action": action,
        "target": target or "",
        "outcome": outcome,
        "detail": detail or "",
        "request_id": request_id or "",
    }

    logger.info(
        "审计：%s %s -> %s（%s）", action, target or "-", outcome, actor or "-",
        extra={
            "event": "audit",
            "action": action,
            "actor": actor or "-",
            "target": target or "",
            "outcome": outcome,
        },
    )

    db = SessionLocal()
    try:
        db.add(AuditLog(**entry))
        db.commit()
    except Exception as e:  # noqa: BLE001 —— 审计失败不能影响业务
        logger.warning("审计写入失败（不影响业务）：%s", e)
        db.rollback()
    finally:
        db.close()


def recent(actor: str | None = None, limit: int = 50) -> list[dict]:
    """查询审计记录；`actor` 为空时返回全部（仅管理员路径调用）。"""
    db = SessionLocal()
    try:
        query = db.query(AuditLog)
        if actor:
            query = query.filter(AuditLog.actor == actor)
        rows = query.order_by(AuditLog.id.desc()).limit(max(1, min(limit, 200))).all()
        return [
            {
                "id": r.id,
                "ts": r.ts.isoformat() if r.ts else "",
                "actor": r.actor,
                "action": r.action,
                "target": r.target,
                "outcome": r.outcome,
                "detail": r.detail,
            }
            for r in rows
        ]
    except Exception as e:  # noqa: BLE001
        logger.warning("审计查询失败：%s", e)
        return []
    finally:
        db.close()
