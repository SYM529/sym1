"""计费模块测试。

为什么值得为"算钱"写测试：评测报告里的成本和线上埋点的成本
来自同一份定义。一旦换算错了，降本 20% 的结论可能只是算错了单位——
这类错误不会报错，只会让所有后续决策建立在错误数字上。
"""

from dataclasses import dataclass

import pytest

from agent import pricing


@dataclass
class FakeUsage:
    """模拟对象形态的 usage_metadata（dict 形态之外的一种常见结构）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TestSumUsage:
    def test_empty(self):
        assert pricing.sum_usage([]) == {
            "input_tokens": 0, "output_tokens": 0, "total_tokens": 0
        }

    def test_dict_form(self):
        messages = [
            type("M", (), {"usage_metadata": {"input_tokens": 10, "output_tokens": 4,
                                              "total_tokens": 14}})(),
            type("M", (), {"usage_metadata": {"input_tokens": 5, "output_tokens": 1,
                                              "total_tokens": 6}})(),
        ]
        assert pricing.sum_usage(messages) == {
            "input_tokens": 15, "output_tokens": 5, "total_tokens": 20
        }

    def test_object_form(self):
        messages = [
            type("M", (), {"usage_metadata": FakeUsage(3, 2, 5)})(),
            type("M", (), {"usage_metadata": FakeUsage(1, 1, 2)})(),
        ]
        assert pricing.sum_usage(messages)["total_tokens"] == 7

    def test_derives_total_when_missing(self):
        messages = [
            type("M", (), {"usage_metadata": {"input_tokens": 7, "output_tokens": 3,
                                              "total_tokens": 0}})(),
        ]
        assert pricing.sum_usage(messages)["total_tokens"] == 10

    def test_messages_without_usage_are_skipped(self):
        messages = [type("M", (), {"usage_metadata": None})()]
        assert pricing.sum_usage(messages)["total_tokens"] == 0


class TestEstimateCost:
    def test_one_million_input_tokens_costs_unit_price(self):
        price = pricing.price_for("deepseek-chat")
        cost = pricing.estimate_cost(
            {"input_tokens": 1_000_000, "output_tokens": 0}, "deepseek-chat"
        )
        assert cost == pytest.approx(price["input"])

    def test_combines_input_and_output(self):
        price = pricing.price_for("deepseek-chat")
        cost = pricing.estimate_cost(
            {"input_tokens": 1_000_000, "output_tokens": 1_000_000}, "deepseek-chat"
        )
        assert cost == pytest.approx(price["input"] + price["output"])

    def test_unknown_model_falls_back_to_default_not_zero(self):
        # 查不到价格也不能记 0，否则"降本"会失去参照
        default = pricing.DEFAULT_PRICE
        cost = pricing.estimate_cost(
            {"input_tokens": 1_000_000, "output_tokens": 0}, "some-unlisted-model"
        )
        assert cost == pytest.approx(default["input"])

    def test_missing_fields_are_treated_as_zero(self):
        assert pricing.estimate_cost({}, "deepseek-chat") == 0.0


class TestMergeUsage:
    def test_accumulates(self):
        total = pricing.empty_usage()
        pricing.merge_usage(total, {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4})
        pricing.merge_usage(total, {"input_tokens": 2, "output_tokens": 2, "total_tokens": 4})

        assert total == {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
