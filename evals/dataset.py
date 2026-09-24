"""评测数据集的加载与静态校验。

刻意不依赖 agent 与任何模型客户端，因此 CI 里不需要 API Key
就能完成数据集完整性校验——这类检查应当能在毫秒级跑完，
而不是绑在需要联网付费的评测流程里。

校验的存在是有原因的：数据集写错会让评测结果完全失真，而且极其隐蔽。
曾因 `expect_tools: []` 配 `tool_match: "any"`（两个空集求交必然为空），
导致安全类用例整批被判失败，表面看是"模型安全能力不足"，
实际是评测配置错误——白排查了很久。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.judges import ASYNC_RULES, RULES

DATASET_PATH = Path(__file__).parent / "dataset.jsonl"
RETRIEVAL_PATH = Path(__file__).parent / "retrieval_dataset.jsonl"

VALID_TOOL_MATCHES = {"any", "none", "exact", "optional"}


def validate_case(obj: dict, line_no: int, seen_ids: set) -> bool:
    """校验单条用例配置，返回是否可用。"""
    problems = []

    case_id = obj.get("id")
    if not case_id:
        problems.append("缺少 id")
    elif case_id in seen_ids:
        problems.append(f"id 重复：{case_id}")
    else:
        seen_ids.add(case_id)

    if not obj.get("input"):
        problems.append("缺少 input")

    expect_tools = obj.get("expect_tools", [])
    tool_match = obj.get("tool_match", "any")
    if not expect_tools and tool_match == "any":
        problems.append(
            "expect_tools 为空时 tool_match 不能为 any（空集相交必然判负），"
            "请改用 none（禁止调用）或 optional（不校验）"
        )
    if tool_match not in VALID_TOOL_MATCHES:
        problems.append(f"未知 tool_match：{tool_match}")

    judge_type = (obj.get("judge") or {}).get("type")
    if judge_type not in RULES and judge_type not in ASYNC_RULES:
        problems.append(f"未知 judge 类型：{judge_type}")

    if problems:
        print(f"[warn] dataset 第 {line_no} 行有问题，已跳过：{'；'.join(problems)}",
              file=sys.stderr)
        return False
    return True


def load_jsonl(path: Path) -> list[dict]:
    """按行读取 JSONL，跳过空行、注释行与解析失败的行。"""
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[warn] {path.name} 第 {line_no} 行 JSON 解析失败，已跳过: {e}",
                      file=sys.stderr)
    return records


def load_dataset(path: Path = DATASET_PATH) -> list[dict]:
    """加载端到端评测集，并做静态校验。"""
    cases = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] dataset 第 {line_no} 行 JSON 解析失败，已跳过: {e}",
                      file=sys.stderr)
                continue
            if validate_case(obj, line_no, seen_ids):
                cases.append(obj)
    return cases


def load_retrieval_dataset(path: Path = RETRIEVAL_PATH) -> list[dict]:
    """加载检索评测集（只做基础校验，相关判定逻辑在 retrieval_eval 中）。"""
    cases = []
    seen_ids: set[str] = set()
    for index, obj in enumerate(load_jsonl(path), start=1):
        case_id = obj.get("id")
        if not case_id:
            print(f"[warn] {path.name} 第 {index} 条缺少 id，已跳过", file=sys.stderr)
            continue
        if case_id in seen_ids:
            print(f"[warn] {path.name} id 重复：{case_id}，已跳过", file=sys.stderr)
            continue
        if not obj.get("query") or not obj.get("gold_keywords"):
            print(f"[warn] {path.name} {case_id} 缺少 query 或 gold_keywords，已跳过",
                  file=sys.stderr)
            continue
        seen_ids.add(case_id)
        cases.append(obj)
    return cases
