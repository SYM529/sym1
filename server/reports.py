"""评测报告的读取与归一化（看板数据源）。

为什么需要归一化这一层
--------------------
`reports/` 里的文件来自三套脚本（端到端评测、检索评测、缓存标定），
字段名各成体系：同样叫 recall 的东西在检索报告里是 `fused_recall@1`，
而端到端报告里根本没有。前端不应该知道这些差别——
"换一种报表格式就要改前端"是典型的把数据格式泄漏给展示层。

读文件的安全边界
----------------
这个模块**不接受任何来自请求的文件名**：接口无参数，
返回目录下全部 `.json` 的归一化结果。即使将来要支持按名查询，
也必须先 resolve 后校验仍白名单目录内（与 uploads 同一套思路）。

哪些文件不进趋势
----------------
`latest.json` 与 `ci_baseline.json` 是**别名**（内容是别的报告的拷贝），
放进趋势线会出现同一个数据点画两次，把"改进了多少"看糊涂。
所以趋势只用真实跑出来的报告，但"最新指标"卡片优先读 latest.json。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./evals/reports"))

# 这些文件是其它报告的拷贝/别名，只用于引用，不进趋势
ALIAS_FILES = {"latest.json", "ci_baseline.json"}


def _safe_dir(root: Path = REPORTS_DIR) -> Path:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"报告目录不存在：{resolved}")
    return resolved


def list_report_files(root: Path = REPORTS_DIR) -> list[Path]:
    """列出全部报告文件。只认 .json，按文件名排序保证多次请求顺序一致。"""
    return sorted(_safe_dir(root).glob("*.json"), key=lambda p: p.name)


def classify(filename: str) -> str:
    if filename.startswith("retrieval"):
        return "retrieval"
    if filename == "cache_calibration.json":
        return "calibration"
    return "eval"


def _latency(summary: dict) -> dict:
    latency = summary.get("latency_sec") or {}
    return {
        "mean": latency.get("mean"),
        "p50": latency.get("p50"),
        "p95": latency.get("p95"),
    }


def normalize_eval_report(path: Path, data: dict) -> dict:
    summary = data.get("summary") or {}
    tokens = summary.get("tokens") or {}
    return {
        "file": path.name,
        "kind": "eval",
        "tag": data.get("tag") or path.stem,
        "generated_at": data.get("generated_at") or "",
        "model": data.get("model"),
        "repeat": data.get("repeat") or summary.get("repeat") or 1,
        "total_cases": summary.get("total_cases"),
        "pass_rate": summary.get("pass_rate"),
        "answer_only_pass_rate": summary.get("answer_only_pass_rate"),
        "tool_call_accuracy": summary.get("tool_call_accuracy"),
        "citation_accuracy": summary.get("citation_accuracy"),
        "stable_pass_rate": summary.get("stable_pass_rate"),
        "flaky_cases": len(summary.get("flaky_cases") or []),
        **_latency(summary),
        "total_tokens": tokens.get("total_tokens"),
        "cost_cny": summary.get("cost_cny"),
        "categories": summary.get("categories") or {},
    }


def normalize_retrieval_report(path: Path, data: dict) -> dict:
    summary = data.get("summary") or {}
    faith = data.get("faithfulness") or {}
    faith_rate = (
        faith.get("faithfulness") if isinstance(faith, dict) else faith
    )
    return {
        "file": path.name,
        "kind": "retrieval",
        "tag": data.get("tag") or path.stem,
        "generated_at": data.get("generated_at") or "",
        "total_cases": summary.get("total_cases"),
        # 融合排序（未精排）与精排后的召回率分开返回，
        # 二者的差值正是"精排带来了多少收益"的直接证据
        "recall_at_1_fused": summary.get("fused_recall@1"),
        "recall_at_3_fused": summary.get("fused_recall@3"),
        "recall_at_1_reranked": summary.get("reranked_recall@1"),
        "recall_at_3_reranked": summary.get("reranked_recall@3"),
        "mrr": summary.get("mrr"),
        "missed_cases": summary.get("missed_cases"),
        "latency_mean_sec": summary.get("latency_mean_sec"),
        "faithfulness": faith_rate,
    }


def normalize_calibration_report(path: Path, data: dict) -> dict:
    return {
        "file": path.name,
        "kind": "calibration",
        "generated_at": data.get("created_at") or "",
        "questions": data.get("questions"),
        "cacheable_questions": data.get("cacheable_questions"),
        "max_distinct_similarity": (data.get("distinct") or {}).get("max_similarity"),
        "min_paraphrase_similarity": (data.get("paraphrase") or {}).get("min_similarity"),
        "recommended_threshold": data.get("recommended_threshold"),
        "chosen_threshold": data.get("chosen_threshold"),
        "false_hits_at_chosen": data.get("false_hits_at_chosen"),
        "threshold_scan": data.get("threshold_scan") or [],
    }


_NORMALIZERS = {
    "eval": normalize_eval_report,
    "retrieval": normalize_retrieval_report,
    "calibration": normalize_calibration_report,
}


def collect_reports(root: Path = REPORTS_DIR) -> dict:
    """一次性返回看板需要的全部数据。

    单个文件损坏只跳过该文件并记日志，绝不让整个看板 500——
    报告目录里混入一个写了一半的文件不应该拖垮展示。
    """
    eval_reports: list[dict] = []
    retrieval_reports: list[dict] = []
    calibration: dict | None = None
    latest: dict | None = None

    for path in list_report_files(root):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            logger.warning("跳过无法解析的报告 %s：%s", path.name, e)
            continue
        if not isinstance(data, dict):
            continue

        kind = classify(path.name)
        report = _NORMALIZERS[kind](path, data)

        if kind == "eval":
            eval_reports.append(report)
            if path.name == "latest.json":
                latest = report
        elif kind == "retrieval":
            retrieval_reports.append(report)
        elif calibration is None:
            calibration = report

    # 趋势只用真实运行产生的报告（别名文件会造成同一点画两次）
    trend = [r for r in eval_reports if r["file"] not in ALIAS_FILES]
    trend.sort(key=lambda r: r["generated_at"] or "")

    # 最新指标：优先 latest.json；没有就取时间最新的
    if latest is None and eval_reports:
        latest = max(eval_reports, key=lambda r: r["generated_at"] or "")
    retrieval_reports.sort(key=lambda r: r["generated_at"] or "")

    return {
        "latest": latest,
        "trend": trend,
        "retrieval": retrieval_reports,
        "calibration": calibration,
    }
