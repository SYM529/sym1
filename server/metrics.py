"""每请求的用量与成本埋点。

补的是什么缺口
-------------
改造之前，成本只有评测脚本能算（`evals/run_eval.py`），
线上运行时完全不知道自己花了多少钱。这意味着：

- 某个用户在刷接口，要等到账单出来才知道；
- 改了 prompt 变贵了，肉眼察觉不到；
- 加了缓存到底省了多少，没有任何数据能证明。

这里把用量按"用户 × 天"聚合进 Redis，于是可以直接回答：
今天花了多少、缓存挡下了多少次调用。
计数用 HINCRBY 原子累加，不需要先读再写。
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

KEY_PREFIX = "usage:"
# 保留 8 天：够看一周趋势，又不至于让 Redis 里堆着过期无用的 key
RETENTION_DAYS = 8
TTL_SECONDS = RETENTION_DAYS * 24 * 3600


def usage_key(user_id: int, day: date) -> str:
    return f"{KEY_PREFIX}{user_id}:{day.isoformat()}"


def record_usage(redis_client, user_id: int, usage: dict, cost: float,
                 cached: bool = False) -> None:
    """记录一次请求的用量。Redis 出错不影响主流程。"""
    if redis_client is None:
        return
    try:
        key = usage_key(user_id, date.today())
        pipe = redis_client.pipeline()
        pipe.hincrby(key, "input_tokens", int(usage.get("input_tokens", 0)))
        pipe.hincrby(key, "output_tokens", int(usage.get("output_tokens", 0)))
        pipe.hincrby(key, "requests", 1)
        if cached:
            pipe.hincrby(key, "cache_hits", 1)
        # 浮点成本累加用 HINCRBYFLOAT，避免精度被整除吞掉
        pipe.hincrbyfloat(key, "cost_cny", float(cost))
        pipe.expire(key, TTL_SECONDS)
        pipe.execute()
    except Exception as e:
        # 埋点失败绝不能影响对话本身
        logger.warning("用量埋点失败：%s", e)


def _to_numbers(raw: dict) -> dict:
    return {
        "input_tokens": int(raw.get("input_tokens", 0) or 0),
        "output_tokens": int(raw.get("output_tokens", 0) or 0),
        "requests": int(raw.get("requests", 0) or 0),
        "cache_hits": int(raw.get("cache_hits", 0) or 0),
        "cost_cny": float(raw.get("cost_cny", 0) or 0),
    }


def read_usage(redis_client, user_id: int, days: int = 7) -> dict:
    """读取用量，返回按天倒序的列表与合计。"""
    empty = {"today": None, "days": [], "total": _to_numbers({})}
    if redis_client is None:
        return empty

    today = date.today()
    try:
        days_data = []
        total = _to_numbers({})
        for offset in range(days):
            day = today - timedelta(days=offset)
            raw = redis_client.hgetall(usage_key(user_id, day)) or {}
            numbers = _to_numbers(raw)
            numbers["date"] = day.isoformat()
            for key, value in numbers.items():
                if key == "date":
                    continue
                if isinstance(value, float):
                    total[key] = round(total[key] + value, 6)
                else:
                    total[key] += value
            days_data.append(numbers)
    except Exception as e:
        logger.warning("读取用量失败：%s", e)
        return empty

    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return {"today": days_data[0] if days_data else None, "days": days_data, "total": total}
