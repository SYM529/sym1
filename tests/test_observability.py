"""结构化日志与 Prometheus 指标的测试。

这些是"可观测性"的地基：日志不带 request_id 就无法串联一次请求，
指标的路径 label 不做归一化就会把 Prometheus 打爆——都要被测试锁住。
"""

import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from starlette.testclient import TestClient

from server import prom
from server.logging_setup import (
    JsonFormatter, RequestContextMiddleware, request_id_var, request_user_var,
)


# ---------------- 结构化日志 ----------------

def _make_record(msg: str, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_output_is_json_with_request_id(self):
        request_id_var.set("rid-abc123")
        formatted = JsonFormatter().format(_make_record("hello"))
        payload = json.loads(formatted)
        assert payload["msg"] == "hello"
        assert payload["request_id"] == "rid-abc123"
        assert payload["level"] == "INFO"
        request_id_var.set("-")

    def test_extra_fields_are_flattened(self):
        record = _make_record("done", event="agent_finish", duration_s=1.5)
        payload = json.loads(JsonFormatter().format(record))
        # 业务字段平铺到顶层，便于检索
        assert payload["event"] == "agent_finish"
        assert payload["duration_s"] == 1.5

    def test_user_context_recorded(self):
        request_user_var.set("alice")
        payload = json.loads(JsonFormatter().format(_make_record("x")))
        assert payload["user"] == "alice"
        request_user_var.set("-")


# ---------------- 中间件 ----------------

def _build_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True, "rid": request_id_var.get()}

    return TestClient(app)


class TestRequestContextMiddleware:
    def test_generates_request_id_and_header(self):
        client = _build_app()
        resp = client.get("/ping")
        assert resp.status_code == 200
        rid = resp.headers.get("x-request-id")
        assert rid, "响应必须带 X-Request-ID"
        # 处理过程中的日志上下文与响应头一致
        assert resp.json()["rid"] == rid

    def test_propagates_incoming_request_id(self):
        client = _build_app()
        resp = client.get("/ping", headers={"X-Request-ID": "client-supplied-99"})
        assert resp.headers["x-request-id"] == "client-supplied-99"

    def test_rejects_malformed_request_id(self):
        """外部传入的 ID 必须校验格式：否则会被用于日志注入。"""
        client = _build_app()
        resp = client.get("/ping", headers={"X-Request-ID": "bad id!@#$"})
        rid = resp.headers["x-request-id"]
        assert rid != "bad id!@#$"
        assert rid.replace("-", "").isalnum()


# ---------------- Prometheus 指标 ----------------

class TestPathNormalization:
    def test_collapses_ids(self):
        assert prom.normalize_path("/api/session/42") == "/api/session/{id}"
        assert (
            prom.normalize_path("/api/knowledge/0f1e2d3c4b5a6978")
            == "/api/knowledge/{id}"
        )

    @pytest.mark.parametrize("path", [
        "/api/session/session_1769000000000",
        "/api/knowledge/u2/0f1e2d3c4b5a69788796a5b4c3d2e1f0",
        "/api/session/f47ac10b-58cc-4372-a567-0e02b2c3d479",
    ])
    def test_high_cardinality_segments(self, path):
        """带 id 的路径必须归一化，否则每个会话都是一个时间序列。"""
        assert "{id}" in prom.normalize_path(path)

    def test_static_paths_untouched(self):
        assert prom.normalize_path("/api/me") == "/api/me"


class TestMetrics:
    def test_render_contains_recorded_metrics(self):
        if not prom.available():
            pytest.skip("prometheus_client 未安装")
        prom.observe_request("/api/me", 200, 0.05)
        prom.record_tokens(10, 20)
        prom.record_cost(0.001)
        prom.record_cache_hit()
        prom.record_error("timeout")

        body, content_type = prom.render()
        assert "text/plain" in content_type
        text = body.decode()
        assert "agent_requests_total" in text
        assert "agent_tokens_total" in text
        assert "agent_cost_cny_total" in text
        assert "agent_cache_hits_total" in text
        assert "agent_errors_total" in text

    def test_metrics_degrade_without_dependency(self, monkeypatch):
        """指标库缺失时不能抛异常——监控是旁路设施。"""
        monkeypatch.setattr(prom, "_AVAILABLE", False)
        prom.observe_request("/api/me", 200, 0.1)
        prom.record_tokens(1, 1)
        body, _ = prom.render()
        assert b"not installed" in body
