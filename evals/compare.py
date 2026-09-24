"""对比两次评测结果，用于回归检测与优化效果验证。

用法：
    python -m evals.compare evals/reports/report_A.json evals/reports/report_B.json
    python -m evals.compare A.json B.json --downgrade-only   # 只看变差的用例
"""

import argparse
import json
import sys
from pathlib import Path


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def compare(baseline: dict, candidate: dict, downgrade_only: bool,
            max_drop: float | None = None):
    b_summary, c_summary = baseline["summary"], candidate["summary"]
    b_map = {r["id"]: r for r in baseline["results"]}
    c_map = {r["id"]: r for r in candidate["results"]}

    print(f"\n对比：{baseline.get('tag')} → {candidate.get('tag')}")
    print(f"模型：{baseline.get('model')} → {candidate.get('model')}\n")

    metrics = [
        ("综合通过率", "pass_rate", _pct),
        ("答案正确率", "answer_only_pass_rate", _pct),
        ("工具调用准确率", "tool_call_accuracy", _pct),
        ("平均延迟(s)", "latency_sec.mean", None),
        ("P95 延迟(s)", "latency_sec.p95", None),
        ("Token 总量", "tokens.total_tokens", None),
    ]

    print(f"  {'指标':<18}{'基线':>14}{'当前':>14}{'变化':>12}")
    print("  " + "-" * 58)
    for label, key, fmt in metrics:
        base_val = dig(b_summary, key)
        curr_val = dig(c_summary, key)
        delta = curr_val - base_val
        render = fmt or (lambda v: f"{v:g}")
        arrow = ""
        if abs(delta) > 1e-9:
            arrow = " ↑" if delta > 0 else " ↓"
        print(f"  {label:<18}{render(base_val):>14}{render(curr_val):>14}"
              f"{render(delta) + arrow:>12}")
    print("  " + "-" * 58)

    all_ids = sorted(set(b_map) | set(c_map))
    improved, regressed, added = [], [], []

    for case_id in all_ids:
        before, after = b_map.get(case_id), c_map.get(case_id)
        if before is None:
            added.append(case_id)
            continue
        if after is None:
            regressed.append((case_id, "用例被移除"))
            continue
        if before["passed"] and not after["passed"]:
            reason = after["answer_reason"] if not after["answer_pass"] else after["tool_reason"]
            regressed.append((case_id, reason))
        elif not before["passed"] and after["passed"]:
            improved.append(case_id)

    print(f"\n  修复 / 提升：{len(improved)} 条")
    for case_id in improved:
        print(f"    + {case_id}")

    print(f"\n  回归 / 变差：{len(regressed)} 条")
    for case_id, reason in regressed[:20]:
        print(f"    - {case_id}: {str(reason)[:70]}")

    if added:
        print(f"\n  新增用例：{len(added)} 条 -> {added}")

    # 逐条回归对 LLM 的采样波动很敏感，CI 里更可靠的门禁是看整体通过率跌幅，
    # 因此这里同时支持 --downgrade-only（逐条）与 --max-drop（整体）两种策略。
    if max_drop is not None:
        drop = b_summary["pass_rate"] - c_summary["pass_rate"]
        if drop > max_drop:
            print(f"\n通过率下降 {drop * 100:.1f} 个百分点，超过容忍度 "
                  f"{max_drop * 100:.1f} 个百分点，门禁失败。")
            return 1
        print(f"\n通过率变化 {-drop * 100:+.1f} 个百分点，在容忍度 "
              f"{max_drop * 100:.1f} 个百分点以内，门禁通过。")

    if downgrade_only and regressed:
        print("\n检测到回归用例，建议不要合并该版本。")
        return 1
    return 0


def dig(data: dict, dotted: str):
    """支持 'latency_sec.mean' 这类点号路径取值。"""
    cursor = data
    for part in dotted.split("."):
        cursor = cursor[part]
    return cursor


def main():
    parser = argparse.ArgumentParser(description="对比两次评测结果")
    parser.add_argument("baseline", help="基线报告 JSON 路径")
    parser.add_argument("candidate", help="待对比报告 JSON 路径")
    parser.add_argument("--downgrade-only", action="store_true",
                        help="存在回归用例时以非零状态退出（对采样波动敏感）")
    parser.add_argument("--max-drop", type=float, default=None,
                        help="允许的通过率下降幅度，如 0.05 表示允许降 5 个百分点，"
                             "超过则以非零退出。CI 门禁推荐用这个而非 --downgrade-only")
    args = parser.parse_args()

    code = compare(
        load(Path(args.baseline)),
        load(Path(args.candidate)),
        args.downgrade_only,
        args.max_drop,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
