"""评测数据集的静态校验测试。

数据集写错会让评测结果完全失真，而且这种错误非常隐蔽——
曾经因为 `expect_tools: []` 配 `tool_match: any`（空集求交必然为空），
导致安全类用例整批被误杀，看起来像是模型安全能力不足，实际是配置错误。
所以要把校验做成测试，而不是靠人工检查。
"""

from pathlib import Path

import pytest

from evals.dataset import (
    DATASET_PATH,
    RETRIEVAL_PATH,
    load_dataset,
    load_retrieval_dataset,
    validate_case,
)


def _count_data_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as f:
        return sum(
            1 for line in f
            if line.strip() and not line.strip().startswith("#")
        )


class TestMainDataset:
    def test_all_cases_pass_validation(self):
        """文件里每一行都应当通过校验，否则说明存在会被静默跳过的问题用例。"""
        cases = load_dataset()
        assert len(cases) == _count_data_lines(DATASET_PATH), \
            "有用例未通过校验被跳过，请检查 stderr 中的 warn"

    def test_case_ids_unique(self):
        cases = load_dataset()
        ids = [c["id"] for c in cases]
        assert len(ids) == len(set(ids))

    def test_has_expected_categories(self):
        categories = {c["category"] for c in load_dataset()}
        expected = {
            "math_direct", "math_multi_step", "time_query", "realtime_info",
            "no_tool_needed", "multi_turn", "multi_tool", "prompt_injection",
            "edge_case", "rag_qa",
        }
        assert expected <= categories, f"缺少类别：{expected - categories}"

    def test_rag_cases_require_citation(self):
        """RAG 用例必须要求引用，否则引用溯源形同虚设。"""
        rag_cases = [c for c in load_dataset() if c["category"] == "rag_qa"]
        assert rag_cases, "没有 RAG 用例"
        # 负样本（未命中）不要求引用，其余都应要求
        requiring = [c for c in rag_cases if c.get("require_citation")]
        assert len(requiring) >= len(rag_cases) - 1


class TestRetrievalDataset:
    def test_valid(self):
        """检索集每一行都应被成功加载，不能被静默跳过。"""
        cases = load_retrieval_dataset()
        assert len(cases) == _count_data_lines(RETRIEVAL_PATH)

    def test_gold_keywords_present(self):
        for case in load_retrieval_dataset():
            assert case["gold_keywords"], f"{case['id']} 缺少 gold_keywords"

    def test_ids_unique(self):
        ids = [c["id"] for c in load_retrieval_dataset()]
        assert len(ids) == len(set(ids))


class TestValidationRules:
    def test_rejects_empty_expect_tools_with_any(self):
        """空期望 + any 会导致空集求交必然失败，必须被拒绝。"""
        assert not validate_case(
            {"id": "x", "input": "q", "expect_tools": [], "tool_match": "any",
             "judge": {"type": "contains", "expected": "a"}},
            line_no=1, seen_ids=set(),
        )

    def test_accepts_empty_expect_tools_with_none(self):
        assert validate_case(
            {"id": "x", "input": "q", "expect_tools": [], "tool_match": "none",
             "judge": {"type": "contains", "expected": "a"}},
            line_no=1, seen_ids=set(),
        )

    def test_rejects_unknown_judge_type(self):
        assert not validate_case(
            {"id": "x", "input": "q", "expect_tools": ["calculate"],
             "tool_match": "any", "judge": {"type": "unknown"}},
            line_no=1, seen_ids=set(),
        )

    def test_rejects_duplicate_ids(self):
        seen = {"dup"}
        assert not validate_case(
            {"id": "dup", "input": "q", "expect_tools": [], "tool_match": "none",
             "judge": {"type": "contains", "expected": "a"}},
            line_no=1, seen_ids=seen,
        )

    def test_rejects_missing_input(self):
        assert not validate_case(
            {"id": "x", "expect_tools": [], "tool_match": "none",
             "judge": {"type": "contains", "expected": "a"}},
            line_no=1, seen_ids=set(),
        )


if __name__ == "__main__":
    pytest.main([__file__])
