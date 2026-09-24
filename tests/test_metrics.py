"""用量埋点测试。

重点是两件事：
1. 聚合算得对——成本是按浮点累加的，若被整数运算吞掉，
   几分钱的成本会直接显示成 0，让"降本"无从衡量。
2. Redis 不可用时不能把对话一起搞挂——埋点是旁路，
   它的失败绝不该影响主流程。
"""

from datetime import date, timedelta

from server import metrics


class FakeRedis:
    """最小可用的 Redis 替身：只实现埋点用到的哈希接口。"""

    def __init__(self):
        self.data: dict[str, dict] = {}

    # pipeline 里的命令立即生效，execute 为空操作。
    # 真实 Redis 的原子性由它自己保证，这里只验证我们的调用逻辑。
    def pipeline(self):
        return self

    def hincrby(self, key, field, amount):
        bucket = self.data.setdefault(key, {})
        bucket[field] = int(bucket.get(field, 0)) + int(amount)

    def hincrbyfloat(self, key, field, amount):
        bucket = self.data.setdefault(key, {})
        bucket[field] = float(bucket.get(field, 0.0)) + float(amount)

    def expire(self, key, ttl):
        return True

    def execute(self):
        return []

    def hgetall(self, key):
        return self.data.get(key, {})


class BrokenRedis:
    def __getattr__(self, name):
        raise RuntimeError("redis is down")


class TestRecord:
    def test_accumulates_across_requests(self):
        r = FakeRedis()
        metrics.record_usage(r, 1, {"input_tokens": 100, "output_tokens": 20}, 0.001)
        metrics.record_usage(r, 1, {"input_tokens": 50, "output_tokens": 10}, 0.002)

        raw = r.hgetall(metrics.usage_key(1, date.today()))
        assert raw["input_tokens"] == 150
        assert raw["output_tokens"] == 30
        assert raw["requests"] == 2
        # 浮点成本不能被整数运算吞掉
        assert abs(raw["cost_cny"] - 0.003) < 1e-9

    def test_cache_hits_counted_only_when_cached(self):
        r = FakeRedis()
        metrics.record_usage(r, 1, {"input_tokens": 10, "output_tokens": 1}, 0.0)
        metrics.record_usage(r, 1, {"input_tokens": 0, "output_tokens": 0}, 0.0, cached=True)

        raw = r.hgetall(metrics.usage_key(1, date.today()))
        assert raw["cache_hits"] == 1
        assert raw["requests"] == 2

    def test_users_are_counted_separately(self):
        r = FakeRedis()
        metrics.record_usage(r, 1, {"input_tokens": 10, "output_tokens": 1}, 0.0)
        metrics.record_usage(r, 2, {"input_tokens": 20, "output_tokens": 2}, 0.0)

        assert r.hgetall(metrics.usage_key(1, date.today()))["input_tokens"] == 10
        assert r.hgetall(metrics.usage_key(2, date.today()))["input_tokens"] == 20


class TestReadUsage:
    def test_returns_today_and_total(self):
        r = FakeRedis()
        metrics.record_usage(r, 1, {"input_tokens": 100, "output_tokens": 50}, 0.005)

        summary = metrics.read_usage(r, 1, days=3)

        assert summary["today"]["input_tokens"] == 100
        assert summary["total"]["requests"] == 1
        assert summary["total"]["total_tokens"] == 150
        assert len(summary["days"]) == 3

    def test_days_are_in_descending_order(self):
        r = FakeRedis()
        summary = metrics.read_usage(r, 1, days=3)
        dates = [d["date"] for d in summary["days"]]

        assert dates == sorted(dates, reverse=True)
        assert dates[0] == date.today().isoformat()
        assert dates[-1] == (date.today() - timedelta(days=2)).isoformat()


class TestDegradation:
    def test_recording_failure_is_swallowed(self):
        # 埋点失败必须不影响对话本身
        metrics.record_usage(BrokenRedis(), 1, {"input_tokens": 5, "output_tokens": 1}, 0.0)

    def test_reading_failure_returns_empty_structure(self):
        summary = metrics.read_usage(BrokenRedis(), 1, days=3)

        assert summary["today"] is None
        assert summary["days"] == []
        assert summary["total"]["requests"] == 0

    def test_none_client_is_accepted(self):
        metrics.record_usage(None, 1, {"input_tokens": 1, "output_tokens": 1}, 0.0)
        assert metrics.read_usage(None, 1)["days"] == []
