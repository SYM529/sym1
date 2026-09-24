"""会话索引与历史读取（侧边栏的数据源）。

为什么需要索引
-------------
会话数据按 `session:{user_id}:{session_id}` 存在 Redis 里，
但 Redis **无法列出某用户有哪些 key**——KEYS/SCAN 是全库操作，
生产环境禁用。所以要一个显式的索引：`sessions:{user_id}` 哈希，
field 是 session_id，value 是 {title, updated_at}。

标题从**首条用户消息**生成，与豆包 / ChatGPT 的做法一致：
会话名在创建时就定下来，之后聊到别的话题也不改名——
改名会让"这个会话是聊什么的"失去锚点。

索引与数据的生命周期不一致怎么办
------------------------------
会话本体有 TTL，索引条目却不会自己消失。
列出时逐个 EXISTS 校验，把已被 TTL 回收的条目顺手从索引里删掉——
否则侧边栏会越用越假：列表还在，点进去全是空会话。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 24
# 会话正文里的附件标记是给模型定位用的，回放历史时不该出现
_ATTACHMENT_MARKER = re.compile(r"\n?\[用户附带了[^\]]*\]\s*$")


def index_key(user_id: int) -> str:
    return f"sessions:{user_id}"


def session_title(message: str) -> str:
    """从首条用户消息生成会话标题。"""
    cleaned = re.sub(r"\s+", " ", (message or "").strip())
    if not cleaned:
        return "新对话"
    if len(cleaned) <= TITLE_MAX_CHARS:
        return cleaned
    return cleaned[:TITLE_MAX_CHARS] + "…"


def record_session(redis_client, user_id: int, session_id: str,
                   first_message: str, session_ttl: int) -> None:
    """登记会话。已存在则只刷新活跃时间，标题保持不变。"""
    try:
        key = index_key(user_id)
        raw = redis_client.hget(key, session_id)
        if raw:
            try:
                info = json.loads(raw)
            except json.JSONDecodeError:
                info = {}
        else:
            info = {"title": session_title(first_message)}
        # 微秒精度：同一秒内登记的多个会话也需要能正确排序
        info["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="microseconds")

        pipe = redis_client.pipeline()
        pipe.hset(key, session_id, json.dumps(info, ensure_ascii=False))
        # 索引比会话本体多留一小时：索引先过期会造成"会话还在、列表没了"
        pipe.expire(key, session_ttl + 3600)
        pipe.execute()
    except Exception as e:
        # 索引是便利功能，失败只影响侧边栏，绝不能影响对话本身
        logger.warning("会话索引更新失败：%s", e)


def remove_session(redis_client, user_id: int, session_id: str) -> None:
    """从索引中移除会话（删除会话时调用）。"""
    try:
        redis_client.hdel(index_key(user_id), session_id)
    except Exception as e:
        logger.warning("会话索引移除失败：%s", e)


def rename_session(redis_client, user_id: int, session_id: str, title: str) -> bool:
    """重命名会话标题。

    只改索引里的展示名，不影响任何消息数据。
    返回 False 表示会话不存在（从未聊过或已被 TTL 回收）——
    这种情况应该明确告诉用户，而不是静默成功。
    """
    try:
        key = index_key(user_id)
        raw = redis_client.hget(key, session_id)
        if raw is None:
            return False
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = {}
        info["title"] = title.strip()[:60]
        redis_client.hset(key, session_id, json.dumps(info, ensure_ascii=False))
        return True
    except Exception as e:
        logger.warning("会话重命名失败：%s", e)
        return False


def list_sessions(redis_client, user_id: int) -> list[dict]:
    """列出会话，按最近活跃倒序；顺带清理已被 TTL 回收的死条目。"""
    key = index_key(user_id)
    try:
        raw = redis_client.hgetall(key) or {}
    except Exception as e:
        logger.warning("读取会话索引失败：%s", e)
        return []

    ids = list(raw.keys())
    if not ids:
        return []

    # EXISTS 逐个校验放在一个 pipeline 里：N 次往返压成 1 次
    pipe = redis_client.pipeline()
    for sid in ids:
        pipe.exists(f"session:{user_id}:{sid}")
    alive_flags = pipe.execute()

    sessions = []
    dead = []
    for sid, alive in zip(ids, alive_flags):
        if not alive:
            dead.append(sid)
            continue
        try:
            info = json.loads(raw[sid])
        except json.JSONDecodeError:
            info = {}
        sessions.append({
            "session_id": sid,
            "title": info.get("title") or sid,
            "updated_at": info.get("updated_at") or "",
        })

    if dead:
        try:
            redis_client.hdel(key, *dead)
        except Exception as e:
            logger.warning("清理过期会话条目失败：%s", e)

    sessions.sort(key=lambda s: s["updated_at"], reverse=True)
    return sessions


def readable_messages(messages) -> list[dict]:
    """把存储的消息转成"回放历史"需要的最小结构。

    过滤规则：
    - system（长对话压缩摘要）：内部实现，不属于聊天内容
    - tool 与带 tool_calls 的中间 AI 消息：工具调用过程不是对话
    - human 的附件标记：那是给模型的定位信息，用户不需要再看一遍
    """
    items = []
    for msg in messages:
        if msg.type == "human":
            content = _ATTACHMENT_MARKER.sub("", msg.content or "")
            if content:
                items.append({"type": "human", "content": content})
        elif msg.type == "ai" and not getattr(msg, "tool_calls", None):
            content = msg.content or ""
            if content:
                items.append({"type": "ai", "content": content})
    return items
