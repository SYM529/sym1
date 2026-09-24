"""Token 计量与成本估算。

为什么要单独成模块，而不是写在 evals 里
--------------------------------------
改造前只有评测脚本会算成本，线上服务完全不知道自己花了多少钱。
要给线上加埋点，最直接的做法是照抄一份价格表——但那是最坏的选择：

两份价格表、两份单位换算逻辑，迟早会漂移。届时"成本上升了 20%"
这种结论将无法归因：到底是请求真的变贵了，还是两边算法不一致？

这里把定义抽出来，评测与线上一份共存：
- `evals/run_eval.py` 用它出评测报告
- `server/` 用它给每次请求计价
"""

from __future__ import annotations

import os

# 价格表：元 / 百万 token。实际以官方定价为准，可用环境变量覆盖。
# 保留 EVAL_* 前缀是为了不破坏已有的评测用法。
DEFAULT_PRICE_INPUT = float(
    os.getenv("PRICE_INPUT", os.getenv("EVAL_PRICE_INPUT", "2.0"))
)
DEFAULT_PRICE_OUTPUT = float(
    os.getenv("PRICE_OUTPUT", os.getenv("EVAL_PRICE_OUTPUT", "8.0"))
)

PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {
        "input": DEFAULT_PRICE_INPUT,
        "output": DEFAULT_PRICE_OUTPUT,
    },
}

# 未登记在表中的模型按主模型价格估算，宁可估得保守，
# 也不要因为查不到价格就把成本记成 0 —— 那会让"降本"彻底失去参照。
DEFAULT_PRICE = {
    "input": DEFAULT_PRICE_INPUT,
    "output": DEFAULT_PRICE_OUTPUT,
}


def empty_usage() -> dict:
    """空的用量结构。"""
    return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}


def price_for(model: str) -> dict[str, float]:
    return PRICING.get(model, DEFAULT_PRICE)


def sum_usage(messages) -> dict:
    """汇总一批消息的 token 用量。

    兼容 `usage_metadata` 为 dict 或对象两种形态：
    不同版本的 LangChain / 不同 provider 返回结构不完全一致，
    这里从严处理，取不到就记 0，而不是让计数崩掉。
    """
    total = empty_usage()
    for msg in messages:
        usage = getattr(msg, "usage_metadata", None)
        if not usage:
            continue
        if isinstance(usage, dict):
            input_tokens = usage.get("input_tokens") or usage.get("input") or 0
            output_tokens = usage.get("output_tokens") or usage.get("output") or 0
            total_tokens = usage.get("total_tokens") or 0
        else:
            input_tokens = getattr(usage, "input_tokens", 0) or 0
            output_tokens = getattr(usage, "output_tokens", 0) or 0
            total_tokens = getattr(usage, "total_tokens", 0) or 0
        total["input_tokens"] += int(input_tokens)
        total["output_tokens"] += int(output_tokens)
        total["total_tokens"] += int(total_tokens)

    if not total["total_tokens"]:
        total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return total


def merge_usage(target: dict, delta: dict) -> dict:
    """把 delta 累加进 target（就地修改并返回）。"""
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        target[key] = target.get(key, 0) + delta.get(key, 0)
    return target


def estimate_cost(usage: dict, model: str = None) -> float:
    """按百万 token 单价估算人民币成本。"""
    price = price_for(model) if model else DEFAULT_PRICE
    return (
        usage.get("input_tokens", 0) / 1_000_000 * price["input"]
        + usage.get("output_tokens", 0) / 1_000_000 * price["output"]
    )
