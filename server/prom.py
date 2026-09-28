"""Prometheus 指标。

设计要点：
1. **依赖可选**：prometheus_client 没装时全部函数退化为空操作。
   监控是旁路设施，绝不能因为指标库缺失让服务起不来——这和 Redis、
   知识库、语义缓存一致的降级策略。
2. **严控 label 基数**：路径里带 id 的（/api/session/{id}）必须归一化，
   否则每个会话一个时间序列，Prometheus 会被打爆（典型线上事故）。
3. 指标只覆盖"排查问题真正要看的"：QPS、延迟、错误、token、成本、缓存命中。
"""

from __future__ import annotations

import re
import time

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest,
    )

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False


# 需要归一化的路径片段：UUID、纯数字、session_xxx
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)
_HEX = re.compile(r"^u\d+/[0-9a-f]{16,}$")
_DIGITS = re.compile(r"^\d+$")


def _looks_like_id(segment: str) -> bool:
    """判断路径片段是否是 id。

    按"长得像 id"来判定，而不是枚举路由：新增接口不必回来改这里。
    """
    if _DIGITS.match(segment):                     # 纯数字主键
        return True
    if _UUID.search(segment):                      # UUID
        return True
    if re.fullmatch(r"[0-9a-f]{16,}", segment, re.I):   # 内容哈希 / doc_id
        return True
    if re.fullmatch(r"u\d+", segment):             # file_id 的用户段（u2）
        return True
    if segment.startswith("session_") and len(segment) > 12:
        return True
    if len(segment) >= 24 and re.fullmatch(r"[A-Za-z0-9_-]+", segment):
        return True                                # 其它长且不透明的字符串
    return False


def normalize_path(path: str) -> str:
    """把具体 id 折叠成占位符，控制 label 基数。

    只对**第三段及以后**生效（/api/<资源>/<id>），
    这样 /api/knowledge（列表）不会被误折叠成 /api/{id}。
    """
    if not path:
        return "-"
    segments = [s for s in path.strip("/").split("/") if s]
    out = []
    for index, seg in enumerate(segments):
        out.append("{id}" if index >= 2 and _looks_like_id(seg) else seg)
    return "/" + "/".join(out)


if _AVAILABLE:
    REQUESTS = Counter(
        "agent_requests_total", "HTTP 请求数", ["path", "status"]
    )
    LATENCY = Histogram(
        "agent_request_duration_seconds", "请求耗时（秒）", ["path"],
        buckets=(0.1, 0.3, 1, 3, 10, 30, 60, 120),
    )
    INFLIGHT = Gauge("agent_requests_inflight", "正在处理的请求数")
    TOKENS = Counter("agent_tokens_total", "模型 token 消耗", ["direction"])
    COST = Counter("agent_cost_cny_total", "模型成本（元）")
    CACHE_HITS = Counter("agent_cache_hits_total", "语义缓存命中次数")
    ERRORS = Counter("agent_errors_total", "错误计数", ["kind"])
    RATE_LIMITED = Counter("agent_rate_limited_total", "被限流拒绝的次数")
    # 熔断器状态：0=closed 1=half_open 2=open
    CIRCUIT_STATE = Gauge("agent_circuit_state", "熔断器状态", ["name"])
    RETRIES = Counter("agent_retries_total", "上游调用重试次数", ["target"])


def observe_request(path: str, status: int, duration_s: float) -> None:
    if not _AVAILABLE:
        return
    normalized = normalize_path(path)
    REQUESTS.labels(path=normalized, status=str(status)).inc()
    LATENCY.labels(path=normalized).observe(duration_s)


def inc_inflight() -> None:
    if _AVAILABLE:
        INFLIGHT.inc()


def dec_inflight() -> None:
    if _AVAILABLE:
        INFLIGHT.dec()


def record_tokens(input_tokens: int, output_tokens: int) -> None:
    if not _AVAILABLE:
        return
    TOKENS.labels(direction="input").inc(max(0, int(input_tokens)))
    TOKENS.labels(direction="output").inc(max(0, int(output_tokens)))


def record_cost(cost_cny: float) -> None:
    if _AVAILABLE:
        COST.inc(max(0.0, float(cost_cny)))


def record_cache_hit() -> None:
    if _AVAILABLE:
        CACHE_HITS.inc()


def record_error(kind: str) -> None:
    if _AVAILABLE:
        ERRORS.labels(kind=kind).inc()


def record_rate_limited() -> None:
    if _AVAILABLE:
        RATE_LIMITED.inc()


_STATE_VALUES = {"closed": 0, "half_open": 1, "open": 2}


def set_circuit_state(name: str, state: str) -> None:
    if _AVAILABLE:
        CIRCUIT_STATE.labels(name=name).set(_STATE_VALUES.get(state, -1))


def record_retry(target: str) -> None:
    if _AVAILABLE:
        RETRIES.labels(target=target).inc()


def render() -> tuple[bytes, str]:
    """返回 (内容, content_type)。指标库缺失时返回空指标。"""
    if not _AVAILABLE:
        return b"# prometheus_client not installed\n", "text/plain; version=0.0.4"
    return generate_latest(), CONTENT_TYPE_LATEST


def available() -> bool:
    return _AVAILABLE


class Timer:
    """简单的耗时统计上下文，便于在流式接口里记录总时长。"""

    def __init__(self) -> None:
        self.start = time.perf_counter()
        self.seconds = 0.0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.start
        return False
