"""限流与并发控制测试。

这组测试守的是三件容易出错的事：

1. **边界**：用满额度的那一次必须放行，第 limit+1 次必须拦下。
   差一错误在这里的后果是"限流形同虚设"或"正常请求被拒"。
2. **时间**：窗口过期后额度要能恢复。用假时钟推进，测试不必真的 sleep 一分钟。
3. **降级**：Redis 挂掉时不能连带搞挂服务，但必须留下 degraded 标记——
   沉默地变成单机限流，是很难排查的一类问题。
"""

import asyncio

import pytest

from server.ratelimit import ConcurrencyGuard, SlidingWindowLimiter


def run(coro):
    """同步跑一个协程。

    项目没有引入 pytest-asyncio，也不打算为一个小小的 await 增加依赖。
    """
    return asyncio.run(coro)


class FakeClock:
    """可控时钟：让"等一个窗口过去"变成一次赋值。"""

    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class BrokenRedis:
    """模拟 Redis 不可用：任何命令都抛错。"""

    def eval(self, *args, **kwargs):
        raise RuntimeError("connection refused")


class StubRedis:
    """替代真实 Redis 执行 Lua。

    滑动窗口的真实语义由 Lua 脚本保证，这里不重复实现一遍——
    本桩件只验证"Python 侧有没有把参数正确传过去、返回值有没有正确解析"，
    也就是只测适配层本身。
    """

    def __init__(self, result=(1, 19, 0)):
        self.result = result
        self.calls: list[dict] = []

    def eval(self, script, numkeys, key, now_ms, window_ms, limit, member):
        self.calls.append({
            "script": script,
            "numkeys": numkeys,
            "key": key,
            "now_ms": now_ms,
            "window_ms": window_ms,
            "limit": limit,
            "member": member,
        })
        return list(self.result)


def make_limiter(redis_client, limit: int = 3, window: float = 60.0):
    clock = FakeClock()
    limiter = SlidingWindowLimiter(
        redis_client, limit=limit, window=window, clock=clock
    )
    return limiter, clock


class TestWindowBoundary:
    def test_allows_up_to_limit_then_blocks(self):
        limiter, _ = make_limiter(None, limit=3)

        for i in range(3):
            assert limiter.check("u1").allowed, f"第 {i + 1} 次应在额度内放行"

        assert limiter.check("u1").allowed is False

    def test_remaining_counts_down(self):
        limiter, _ = make_limiter(None, limit=3)

        assert limiter.check("u1").remaining == 2
        assert limiter.check("u1").remaining == 1
        assert limiter.check("u1").remaining == 0

    def test_quota_recovers_after_window(self):
        limiter, clock = make_limiter(None, limit=2, window=60)

        assert limiter.check("u1").allowed
        assert limiter.check("u1").allowed
        assert limiter.check("u1").allowed is False

        clock.advance(59)
        # 还没到最早的两次滑出窗口
        assert limiter.check("u1").allowed is False

        clock.advance(2)
        # 此时最早两次已滑出窗口，额度恢复
        assert limiter.check("u1").allowed is True

    def test_retry_after_is_positive_and_bounded(self):
        limiter, _ = make_limiter(None, limit=1, window=60)

        limiter.check("u1")
        blocked = limiter.check("u1")

        assert blocked.allowed is False
        assert 0 < blocked.retry_after <= 60


class TestIsolationAndDegradation:
    def test_identities_have_separate_quotas(self):
        limiter, _ = make_limiter(None, limit=1)

        assert limiter.check("alice").allowed
        assert limiter.check("bob").allowed
        # alice 已用满，但不应影响 bob 之外的人被误伤，反之亦然
        assert limiter.check("alice").allowed is False
        assert limiter.check("bob").allowed is False

    def test_redis_failure_degrades_to_local_with_marker(self):
        limiter, _ = make_limiter(BrokenRedis(), limit=2)

        first = limiter.check("u1")
        assert first.allowed is True
        # 必须留下标记：否则"限流悄悄变成了单机"是无从察觉的
        assert first.degraded is True

        limiter.check("u1")
        assert limiter.check("u1").allowed is False

    def test_zero_limit_disables_rate_limiting(self):
        limiter, _ = make_limiter(None, limit=0)

        for _ in range(50):
            assert limiter.check("u1").allowed


class TestRedisAdapter:
    def test_passes_correct_arguments(self):
        stub = StubRedis(result=(1, 19, 0))
        limiter, _ = make_limiter(stub, limit=20, window=60)

        result = limiter.check("42")

        call = stub.calls[0]
        assert call["key"] == "ratelimit:42"
        assert call["numkeys"] == 1
        assert call["window_ms"] == 60_000
        assert call["limit"] == 20
        assert result.allowed is True
        assert result.remaining == 19

    def test_converts_retry_after_to_seconds(self):
        stub = StubRedis(result=(0, 0, 3500))
        limiter, _ = make_limiter(stub, limit=1)

        result = limiter.check("42")

        assert result.allowed is False
        assert result.retry_after == 3.5


class TestConcurrencyGuard:
    def test_blocks_when_full(self):
        guard = ConcurrencyGuard(limit=2)

        assert run(guard.acquire_nowait()) is True
        assert run(guard.acquire_nowait()) is True
        assert run(guard.acquire_nowait()) is False
        assert guard.active == 2

    def test_release_frees_slot(self):
        guard = ConcurrencyGuard(limit=1)

        assert run(guard.acquire_nowait()) is True
        assert run(guard.acquire_nowait()) is False

        guard.release()

        assert guard.active == 0
        assert run(guard.acquire_nowait()) is True

    def test_release_never_goes_negative(self):
        guard = ConcurrencyGuard(limit=2)

        guard.release()  # 没有持有却释放，不能把计数器搞成负数

        assert guard.active == 0
        assert run(guard.acquire_nowait()) is True

    @pytest.mark.parametrize("calls", [1, 5, 20])
    def test_zero_limit_means_unlimited(self, calls):
        guard = ConcurrencyGuard(limit=0)

        for _ in range(calls):
            assert run(guard.acquire_nowait()) is True
