"""熔断与重试。

为什么需要这一层：
上游模型/检索服务会抖动。没有保护时，一次抖动表现为"每个请求都硬等到超时"，
既拖垮用户体验，又把并发名额占满——本来只是部分失败，演变成整体不可用。

两个机制各管一段：
- **重试**：对付**偶发**抖动（网络闪断、429）——重试一次通常就好了
- **熔断**：对付**持续**故障（服务商整体不可用）——快速失败，别再白白等超时

放在 agent 层而不是 server 层：视觉模型、Embedding 这些调用发生在 agent 内部，
把能力放这边才能被它们直接用，同时不引入 server→agent 之外的反向依赖。
"""

from __future__ import annotations

import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)

# 判定为"可重试"的特征：这些错误重试有概率成功
_TRANSIENT_HINTS = (
    "timeout", "timed out", "connection", "temporarily", "429",
    "500", "502", "503", "504", "rate limit", "overloaded",
)


def is_transient(error: BaseException) -> bool:
    """判断错误是否值得重试。

    只对"过一会儿可能就好了"的错误重试。参数错误、鉴权失败、内容被拒
    这类确定性错误重试一百次也没用，只会放大延迟和成本。
    """
    if isinstance(error, (asyncio.TimeoutError, ConnectionError)):
        return True
    text = f"{type(error).__name__}: {error}".lower()
    return any(hint in text for hint in _TRANSIENT_HINTS)


class CircuitBreaker:
    """简单三态熔断器（closed → open → half-open → closed）。

    刻意不做滑动窗口统计：这个规模下，连续失败计数已经足够表达
    "上游是不是挂了"，而且状态清晰、易测、易解释。
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = 5,
                 reset_timeout: float = 60.0) -> None:
        self.name = name
        self.failure_threshold = max(1, failure_threshold)
        self.reset_timeout = reset_timeout
        self._state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._on_change = None

    # ---------- 查询 ----------

    @property
    def state(self) -> str:
        # 熔断到期后自动进入半开：放一个请求去探活
        if self._state == self.OPEN and self._opened_at:
            if time.monotonic() - self._opened_at >= self.reset_timeout:
                self._transition(self.HALF_OPEN)
        return self._state

    def allow(self) -> bool:
        return self.state != self.OPEN

    def snapshot(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self._failures,
            "threshold": self.failure_threshold,
        }

    def set_on_change(self, callback) -> None:
        """状态变化回调（用于打日志 / 更新指标）。"""
        self._on_change = callback

    # ---------- 记录 ----------

    def record_success(self) -> None:
        if self._state in (self.HALF_OPEN, self.OPEN):
            self._failures = 0
            self._transition(self.CLOSED)
        else:
            self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self._state == self.HALF_OPEN:
            # 探活请求也失败：立即回到熔断，继续等待
            self._open()
            return
        if self._failures >= self.failure_threshold:
            self._open()

    # ---------- 内部 ----------

    def _open(self) -> None:
        self._opened_at = time.monotonic()
        self._transition(self.OPEN)

    def _transition(self, new_state: str) -> None:
        if new_state == self._state:
            return
        old = self._state
        self._state = new_state
        logger.warning(
            "熔断器 %s：%s -> %s（连续失败 %d）",
            self.name, old, new_state, self._failures,
            extra={
                "event": "circuit_state_change",
                "breaker": self.name,
                "from": old,
                "to": new_state,
            },
        )
        if self._on_change:
            try:
                self._on_change(self.name, new_state)
            except Exception:  # pragma: no cover
                pass


_BREAKERS: dict[str, CircuitBreaker] = {}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """按名字取共享熔断器（同名的调用点共享一个状态）。"""
    breaker = _BREAKERS.get(name)
    if breaker is None:
        breaker = CircuitBreaker(name, **kwargs)
        _BREAKERS[name] = breaker
    return breaker


def reset_breakers() -> None:
    """清空注册表（测试用）。"""
    _BREAKERS.clear()


async def retry_call(
    func,
    *args,
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    retry_if=is_transient,
    on_retry=None,
    **kwargs,
):
    """带指数退避 + 抖动的异步重试。

    抖动（jitter）很重要：多个请求同时失败时，如果没有随机成分，
    它们会在同一时刻一起重试，形成新的尖峰。
    """
    last_error: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 —— 统一交给 retry_if 判定
            last_error = e
            if attempt >= attempts or not retry_if(e):
                raise
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            delay = delay * (0.5 + random.random() / 2)  # 抖动
            logger.warning(
                "调用失败，%.2fs 后重试（第 %d/%d 次）：%s",
                delay, attempt, attempts, e,
                extra={
                    "event": "retry",
                    "attempt": attempt,
                    "delay_s": round(delay, 2),
                },
            )
            if on_retry:
                try:
                    on_retry(attempt, e)
                except Exception:  # pragma: no cover
                    pass
            await asyncio.sleep(delay)
    raise last_error  # pragma: no cover
