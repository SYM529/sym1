"""评测报告归一化测试。

为什么值得测"读个 JSON"：看板的数据口径是由这一层决定的。
归一化错了，趋势图上的"通过率下降"可能只是字段读错——
展示层的错误不会报错，只会让人做出错误判断。

另一个必须锁死的是**别名文件的处理**：
latest.json / ci_baseline.json 是别的报告的拷贝，
混进趋势线会出现同一个数据点画两次，"改进了多少"就看不出来了。
"""

import json

import pytest

from server import reports


@pytest.fixture
def report_dir(tmp_path, monkeypatch):
    """构造一个受控的报告目录。

    归一化函数都接受 root 参数，测试不需要动模块级常量，
    也不用 reload 模块。
    """
    def write(name: str, payload: dict):
        (tmp_path / name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    write.name = write  # 让 fixture 可以直接以 report_dir.write(...) 使用
    return tmp_path


def eval_payload(tag: str, generated_at: str, pass_rate=1.0, tool_acc=0.9):
    return {
        "tag": tag,
        "model": "deepseek-chat",
        "repeat": 2,
        "generated_at": generated_at,
        "summary": {
            "total_cases": 100,
            "passed_cases": int(100 * pass_rate),
            "pass_rate": pass_rate,
            "answer_only_pass_rate": pass_rate,
            "tool_call_accuracy": tool_acc,
            "citation_accuracy": 1.0,
            "citation_cases": 10,
            "latency_sec": {"mean": 2.0, "p50": 1.8, "p95": 3.1, "max": 4.0},
            "tokens": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "cost_cny": 0.5,
            "categories": {"math_direct": {"total": 10, "passed": 9, "pass_rate": 0.9}},
            "repeat": 2,
            "stable_pass_rate": pass_rate,
            "flaky_cases": [],
        },
    }


class TestClassification:
    def test_retrieval_reports_are_recognized_by_prefix(self):
        assert reports.classify("retrieval_20260922.json") == "retrieval"

    def test_calibration_report(self):
        assert reports.classify("cache_calibration.json") == "calibration"

    def test_everything_else_is_eval(self):
        assert reports.classify("react-v2.json") == "eval"
        assert reports.classify("latest.json") == "eval"


class TestNormalizeEval:
    def test_fields_are_mapped(self, tmp_path):
        path = tmp_path / "a.json"
        path.write_text(json.dumps(eval_payload("run-a", "2026-09-22T10:00:00")),
                        encoding="utf-8")

        normalized = reports.normalize_eval_report(path, json.loads(path.read_text(encoding="utf-8")))

        assert normalized["tag"] == "run-a"
        assert normalized["generated_at"] == "2026-09-22T10:00:00"
        assert normalized["pass_rate"] == 1.0
        assert normalized["tool_call_accuracy"] == 0.9
        assert normalized["p50"] == 1.8
        assert normalized["p95"] == 3.1
        assert normalized["total_tokens"] == 2
        assert normalized["cost_cny"] == 0.5
        assert "math_direct" in normalized["categories"]

    def test_missing_summary_does_not_crash(self, tmp_path):
        # 报告可能写到一半被中断：缺字段应归一成空值，而不是抛异常
        path = tmp_path / "broken.json"
        path.write_text(json.dumps({"tag": "broken"}), encoding="utf-8")

        normalized = reports.normalize_eval_report(
            path, json.loads(path.read_text(encoding="utf-8"))
        )

        assert normalized["pass_rate"] is None
        assert normalized["categories"] == {}


class TestCollect:
    def _eval(self, path, **kwargs):
        path.write_text(
            json.dumps(eval_payload(**kwargs), ensure_ascii=False), encoding="utf-8"
        )

    def test_trend_is_sorted_by_time(self, tmp_path):
        self._eval(tmp_path / "b.json", tag="b", generated_at="2026-09-22T12:00:00")
        self._eval(tmp_path / "a.json", tag="a", generated_at="2026-09-22T09:00:00")

        result = reports.collect_reports(tmp_path)

        assert [r["tag"] for r in result["trend"]] == ["a", "b"]
        assert result["latest"]["tag"] == "b"

    def test_alias_files_do_not_pollute_the_trend(self, tmp_path):
        self._eval(tmp_path / "run.json", tag="run", generated_at="2026-09-22T10:00:00")
        # latest.json 是 run.json 的拷贝：进趋势就会把同一个点画两次
        (tmp_path / "latest.json").write_text(
            json.dumps(eval_payload("run", "2026-09-22T10:00:00")), encoding="utf-8"
        )

        result = reports.collect_reports(tmp_path)

        assert [r["file"] for r in result["trend"]] == ["run.json"]
        # 但"最新指标"卡片仍然优先读 latest.json
        assert result["latest"]["file"] == "latest.json"

    def test_retrieval_and_calibration_are_separated(self, tmp_path):
        (tmp_path / "retrieval_r1.json").write_text(json.dumps({
            "tag": "r1", "generated_at": "2026-09-22T10:00:00",
            "summary": {"total_cases": 36, "fused_recall@1": 0.861,
                        "reranked_recall@1": 0.972, "mrr": 0.92},
            "faithfulness": {"total": 36, "passed": 36, "faithfulness": 1.0},
        }), encoding="utf-8")
        (tmp_path / "cache_calibration.json").write_text(json.dumps({
            "created_at": "2026-09-22T11:00:00",
            "questions": 148, "cacheable_questions": 132,
            "distinct": {"max_similarity": 0.8763},
            "paraphrase": {"min_similarity": 0.5983},
            "recommended_threshold": 0.92,
            "chosen_threshold": 0.92,
            "false_hits_at_chosen": 0,
        }), encoding="utf-8")

        result = reports.collect_reports(tmp_path)

        assert result["trend"] == []
        assert result["retrieval"][0]["recall_at_1_fused"] == 0.861
        assert result["retrieval"][0]["recall_at_1_reranked"] == 0.972
        assert result["retrieval"][0]["faithfulness"] == 1.0
        assert result["calibration"]["chosen_threshold"] == 0.92
        assert result["calibration"]["false_hits_at_chosen"] == 0

    def test_corrupted_file_is_skipped_not_fatal(self, tmp_path):
        # 半截 JSON 不应该让整个看板 500
        (tmp_path / "good.json").write_text(
            json.dumps(eval_payload("g", "2026-09-22T10:00:00")), encoding="utf-8"
        )
        (tmp_path / "bad.json").write_text('{"tag": "oops"', encoding="utf-8")

        result = reports.collect_reports(tmp_path)

        assert len(result["trend"]) == 1
        assert result["trend"][0]["tag"] == "g"

    def test_latest_falls_back_to_newest_when_no_alias(self, tmp_path):
        self._eval(tmp_path / "old.json", tag="old", generated_at="2026-09-20T10:00:00")
        self._eval(tmp_path / "new.json", tag="new", generated_at="2026-09-22T10:00:00")

        result = reports.collect_reports(tmp_path)

        assert result["latest"]["tag"] == "new"


class TestDirectorySafety:
    def test_missing_directory_raises_a_clear_error(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            reports.collect_reports(tmp_path / "not-exist")
