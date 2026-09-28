"""结构化日志与请求上下文。

为什么要结构化：容器里 stdout 的纯文本日志只能靠 grep 拼凑线索；
线上一次"某个用户说回答很慢"的排查，需要能把**同一次请求**的所有日志
串起来看——所以每条日志都带上 request_id，并输出 JSON 便于采集
（ELK / Loki / 云日志服务都直接吃 JSON）。

为什么用裸 ASGI 中间件而不是 BaseHTTPMiddleware：
后者会把响应包装成新的迭代流，对 SSE 这类长连接有缓冲与内存增长风险。
SSE 是本项目的核心链路，不能为日志引入不确定性。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import uuid
from contextvars import ContextVar
from logging import LogRecord

# 当前请求 ID。ContextVar 按 task 自动隔离，并发请求互不串扰
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# 已登录用户 ID（鉴权通过后由 main.py 写入，便于日志定位到具体账号）
request_user_var: ContextVar[str] = ContextVar("request_user", default="-")

_HEADER_NAME = "x-request-id"
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def current_request_id() -> str:
    return request_id_var.get()


class JsonFormatter(logging.Formatter):
    """把日志渲染成单行 JSON。

    额外字段通过 `logger.info("...", extra={"event": "xxx"})` 传入，
    会被平铺进 JSON 顶层，便于检索。
    """

    # 标准库中已经有的键，不需要重复平铺
    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
        "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
        "created", "msecs", "relativeCreated", "thread", "threadName",
        "processName", "process", "getMessage", "message", "asctime",
        "taskName",
    }

    def format(self, record: LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_var.get()),
            "user": getattr(record, "request_user", request_user_var.get()),
        }
        # 业务自定义字段平铺进顶层
        for key, value in record.__dict__.items():
            if key not in self._RESERVED and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class RequestContextFilter(logging.Filter):
    """把上下文里的 request_id / user 注入每条日志记录。"""

    def filter(self, record: LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        if not getattr(record, "request_user", None):
            record.request_user = request_user_var.get()
        return True


def setup_logging(level: str | None = None, json_output: bool | None = None) -> None:
    """配置根日志器。

    - `LOG_FORMAT=text` 可切回普通文本（本地开发更易读）
    - `LOG_LEVEL` 控制级别，默认 INFO
    """
    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO")
    if json_output is None:
        json_output = os.getenv("LOG_FORMAT", "json").lower() != "text"

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-7s %(name)s "
                "[rid=%(request_id)s] %(message)s"
            )
        )
    handler.addFilter(RequestContextFilter())
    root.addHandler(handler)


def _normalize_incoming(raw: str | None) -> str | None:
    """只接受格式安全的外部 request_id，避免日志注入。"""
    if not raw:
        return None
    raw = raw.strip()
    return raw if _ID_PATTERN.match(raw) else None


class RequestContextMiddleware:
    """裸 ASGI 中间件：分配/透传 request_id，记录访问日志。"""

    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("access")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        rid = _normalize_incoming(headers.get(_HEADER_NAME)) or uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)

        start = time.perf_counter()
        status_holder = {"code": 0}

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message.get("status", 0)
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", rid.encode()))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.logger.info(
                "%s %s -> %s",
                scope.get("method"), scope.get("path"), status_holder["code"],
                extra={
                    "event": "http_request",
                    "method": scope.get("method"),
                    "path": scope.get("path"),
                    "status": status_holder["code"],
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
