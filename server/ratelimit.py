"""请求限流与并发控制。

为什么 Agent 接口尤其需要它
---------------------------
Agent 请求和普通的 CRUD 请求不是一回事：一次对话背后可能是
若干轮 LLM 调用，外加检索、精排、联网搜索这些外部 API。
单位成本高出两三个数量级，响应时间还不可预测。

- 没有限流：一个用户写个 for 循环就能把整队配额刷爆，
  其他人看到的是"服务很卡"，实际是被一个人的请求挤满了。
- 没有并发上限：上游一旦变慢，进程里会堆积大量正在流式等待的请求，
  连接池和内存被慢慢吃干，雪崩往往从这里开始。

为什么不用 slowapi
-----------------
slowapi 的计数存在单个进程的内存里。本项目的会话本来就依赖 Redis，
限流同样集中计数，多副本部署时才能共享同一个额度。
Redis 不可用时退回进程内计数——与会话存储保持一致的降级策略：
宁可限流不准，也不让整个服务因为限流组件挂掉而不可用。

为什么是滑动窗口而不是固定窗口
-----------------------------
固定窗口在边界处最多放过 2 倍流量（0:59 打满、1:00 又能打满）。
滑动窗口按每次请求的时间戳精确计算，不会出现这种突刺。
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass

logger = logging.getLogger(__name__)

KEY_PREFIX = "ratelimit:"

# 环境变量统一在这里读取，方便按部署环境调整而不改代码
MAX_REQUESTS_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "20"))
WINDOW_SECONDS = float(os.getenv("RATE_LIMIT_WINDOW", "60"))
MAX_CONCURRENCY = int(os.getenv("AGENT_MAX_CONCURRENCY", "8"))


@dataclass(frozen=True)
class LimitResult:
    """限流判定结果。

    degraded=True 表示本次是由进程内存兜底计算的，
    多副本之间不会共享额度——记录下来是为了让运维知道发生了什么，
    而不是让它悄悄失真。
    """

    allowed: bool
    remaining: int
    retry_after: float = 0.0
    degraded: bool = False


# 滑动窗口计数，用 Lua 保证"清理-统计-写入"三步的原子性。
# 拆成多条 Redis 命令在高并发下会互相穿插，导致实际放行量超出额度。
_LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)

if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('PEXPIRE', key, window)
    return {1, limit - count - 1, 0}
end

-- 已超额度：用最老那条记录的到期时间告诉客户端还要等多久
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = 0
if oldest[2] then
    retry = (oldest[2] + window) - now
end
return {0, 0, retry}
"""


class SlidingWindowLimiter:
    """基于 Redis 有序集合的滑动窗口限流器。

    Redis 不可用时分两级降级：
    1. Redis 抛错 —— 退回进程内计数，标记 degraded；
    2. limit <= 0  —— 视为关闭限流，直接放行（便于本地调试）。
    """

    def __init__(self, redis_client, limit: int = MAX_REQUESTS_PER_MIN,
                 window: float = WINDOW_SECONDS, clock=time.time):
        self._redis = redis_client
        self._limit = limit
        self._window = window
        # 注入 clock 是为了让单元测试无需真的 sleep 一分钟
        self._clock = clock
        self._local: dict[str, list[float]] = {}
        self._local_lock = threading.Lock()
        self._warned = False

    @property
    def limit(self) -> int:
        return self._limit

    def check(self, identity: str) -> LimitResult:
        """判定 identity（通常是 user_id）本次请求是否被放行。"""
        if self._limit <= 0:
            return LimitResult(allowed=True, remaining=0)

        now = self._clock()
        key = f"{KEY_PREFIX}{identity}"

        if self._redis is not None:
            try:
                return self._check_redis(key, now)
            except Exception as e:  # RedisError 及其它连接问题一律降级
                if not self._warned:
                    logger.warning(
                        "限流降级为进程内计数：%s", e, exc_info=False
                    )
                    self._warned = True
                return self._check_local(key, now, degraded=True)

        return self._check_local(key, now)

    def _check_redis(self, key: str, now: float) -> LimitResult:
        now_ms = int(now * 1000)
        allowed, remaining, retry_ms = self._redis.eval(
            _LUA_SLIDING_WINDOW,
            1,
            key,
            now_ms,
            int(self._window * 1000),
            self._limit,
            f"{now_ms}-{uuid.uuid4().hex}",
        )
        return LimitResult(
            allowed=bool(allowed),
            remaining=int(remaining),
            retry_after=max(0.0, int(retry_ms) / 1000.0),
        )

    def _check_local(self, key: str, now: float, degraded: bool = False) -> LimitResult:
        cutoff = now - self._window
        with self._local_lock:
            stamps = [t for t in self._local.get(key, ()) if t > cutoff]
            if len(stamps) < self._limit:
                stamps.append(now)
                self._local[key] = stamps
                return LimitResult(
                    allowed=True,
                    remaining=self._limit - len(stamps),
                    degraded=degraded,
                )
            self._local[key] = stamps
            retry = max(0.0, stamps[0] + self._window - now)
            return LimitResult(
                allowed=False, remaining=0, retry_after=retry, degraded=degraded
            )


class ConcurrencyGuard:
    """限制同时在跑的 Agent 请求数。

    刻意**不让请求排队等待**：排队的请求占着连接却不干活，
    只会让积压更严重。取不到名额立刻返回 429，让客户端稍后重试。

    这里用普通计数而非 asyncio.Semaphore：
    检查与自增之间没有 await，在单线程事件循环里天然是原子的，
    所以不需要锁，也不会遇到 `wait_for(timeout=0)` 那种调度歧义。
    """

    def __init__(self, limit: int = MAX_CONCURRENCY):
        self._limit = limit
        self._active = 0

    @property
    def active(self) -> int:
        return self._active

    async def acquire_nowait(self) -> bool:
        if self._limit <= 0:
            return True
        if self._active >= self._limit:
            return False
        self._active += 1
        return True

    def release(self) -> None:
        self._active = max(0, self._active - 1)


def build_limiter(redis_client) -> SlidingWindowLimiter:
    """构造限流器。抽成工厂函数方便测试时替换实现。"""
    return SlidingWindowLimiter(redis_client, limit=MAX_REQUESTS_PER_MIN)


def build_guard() -> ConcurrencyGuard:
    return ConcurrencyGuard(limit=MAX_CONCURRENCY)
