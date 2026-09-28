"""熔断与重试的测试。

这两个机制的错误实现会导致**故障放大**：该重试的不重试、不该重试的狂重试、
熔断后不放行探活请求——所以状态机的每一步都要被测试锁住。
"""

import asyncio

import pytest

from agent.resilience import (
    CircuitBreaker, get_breaker, is_transient, reset_breakers, retry_call,
)


# ---------------- 瞬时错误判定 ----------------

class TestTransientDetection:
    def test_timeout_is_transient(self):
        assert is_transient(asyncio.TimeoutError())

    def test_connection_error_is_transient(self):
        assert is_transient(ConnectionError("reset by peer"))

    @pytest.mark.parametrize("message", [
        "429 rate limit exceeded", "503 Service Unavailable",
        "connection timeout", "server overloaded",
    ])
    def test_provider_errors(self, message):
        assert is_transient(RuntimeError(message))

    @pytest.mark.parametrize("message", [
        "401 unauthorized", "invalid api key", "content policy violation",
    ])
    def test_deterministic_errors_not_transient(self, message):
        """确定性错误重试一百次也没用，只会放大延迟与成本。"""
        assert not is_transient(RuntimeError(message))


# ---------------- 熔断状态机 ----------------

class TestCircuitBreaker:
    def test_stays_closed_under_threshold(self):
        breaker = CircuitBreaker("t1", failure_threshold=3)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreaker.CLOSED
        assert breaker.allow()

    def test_opens_at_threshold(self):
        breaker = CircuitBreaker("t2", failure_threshold=3)
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == CircuitBreaker.OPEN
        assert not breaker.allow(), "熔断后必须拒绝请求"

    def test_half_open_after_cooldown(self):
        breaker = CircuitBreaker("t3", failure_threshold=2, reset_timeout=0.05)
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == CircuitBreaker.OPEN

        # 等过冷却期后应放一个请求去探活
        import time
        time.sleep(0.06)
        assert breaker.state == CircuitBreaker.HALF_OPEN
        assert breaker.allow()

    def test_success_closes_again(self):
        breaker = CircuitBreaker("t4", failure_threshold=1, reset_timeout=0.05)
        breaker.record_failure()
        assert breaker.state == CircuitBreaker.OPEN
        import time
        time.sleep(0.06)
        assert breaker.state == CircuitBreaker.HALF_OPEN
        breaker.record_success()
        assert breaker.state == CircuitBreaker.CLOSED

    def test_failure_in_half_open_reopens(self):
        breaker = CircuitBreaker("t5", failure_threshold=1, reset_timeout=0.05)
        breaker.record_failure()
        import time
        time.sleep(0.06)
        assert breaker.state == CircuitBreaker.HALF_OPEN
        breaker.record_failure()
        assert breaker.state == CircuitBreaker.OPEN, "探活失败必须立刻重新熔断"

    def test_state_change_callback(self):
        events = []
        breaker = CircuitBreaker("t6", failure_threshold=1)
        breaker.set_on_change(lambda name, state: events.append(state))
        breaker.record_failure()
        assert events == [CircuitBreaker.OPEN]


# ---------------- 重试 ----------------

class TestRetryCall:
    def test_returns_on_first_success(self):
        async def ok():
            return "done"

        assert asyncio.run(retry_call(ok, attempts=3)) == "done"

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise ConnectionError("timeout")
            return "recovered"

        result = asyncio.run(
            retry_call(flaky, attempts=3, base_delay=0.001, max_delay=0.002)
        )
        assert result == "recovered"
        assert calls["n"] == 3

    def test_gives_up_after_attempts(self):
        calls = {"n": 0}

        async def always_fail():
            calls["n"] += 1
            raise ConnectionError("timeout")

        with pytest.raises(ConnectionError):
            asyncio.run(
                retry_call(always_fail, attempts=3, base_delay=0.001, max_delay=0.002)
            )
        assert calls["n"] == 3, "重试次数必须严格等于 attempts"

    def test_no_retry_for_deterministic_error(self):
        calls = {"n": 0}

        async def bad_request():
            calls["n"] += 1
            raise ValueError("401 unauthorized")

        with pytest.raises(ValueError):
            asyncio.run(retry_call(bad_request, attempts=3, base_delay=0.001))
        assert calls["n"] == 1, "确定性错误不该重试"


# ---------------- 注册表 ----------------

class TestRegistry:
    def test_shared_per_name(self):
        reset_breakers()
        a = get_breaker("shared", failure_threshold=1)
        b = get_breaker("shared")
        assert a is b
        a.record_failure()
        assert b.state == CircuitBreaker.OPEN
        reset_breakers()
