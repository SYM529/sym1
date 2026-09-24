"""用评测集标定语义缓存的相似度阈值。

为什么不能凭感觉定一个 0.8
-------------------------
阈值定低了，语义相近但**不同**的问题会互相命中——
"北京今天天气"和"北京明天天气"相似度极高，误命中就是给用户一个
看起来很自信的错答案，这比多花几分钱严重得多。
阈值定高了，缓存形同虚设，白搭一次 embedding 调用。

所以阈值必须落在两个数字之间：

    不同问题的最大相似度  <  阈值  <  同义改写的最小相似度

本项目在 RAG 精排阈值上已经用过同样的做法（RAG_MIN_SCORE 由实测分布标定），
这里沿用：用数据说话，不拍脑袋。

用法
----
    python -m evals.cache_calibrate
    python -m evals.cache_calibrate --threshold 0.90
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path

for _stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
    if _stream is not None and hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from evals.dataset import load_dataset  # noqa: E402
# 直接复用服务端实现：标定结果必须与实际判定逻辑一致，
# 否则"标定说 0 误命中"和线上行为会是两回事。
from server.cache import number_signature  # noqa: E402

REPORT_DIR = Path(__file__).parent / "reports"

# 人工构造的同义改写对：代表"应当命中"的情形。
# 第三列表示答案是否会被缓存——问时间的答案随时间变化，服务端不缓存它们，
# 统计覆盖率时应当排除，否则会把"本就不该命中"的样本算进收益。
PARAPHRASE_PAIRS: list[tuple[str, str, bool]] = [
    ("帮我算一下 123 乘以 456", "123 乘 456 等于多少？", True),
    ("1TB 等于多少 GB", "请问 1TB 是多少 GB", True),
    ("现在几点了", "告诉我现在的时间", False),
    ("今天几号", "今天的日期是多少", False),
    ("什么是 ReAct", "给我解释一下 ReAct 是什么", True),
    ("会话的 TTL 是多久", "聊天记录会保存多长时间", True),
    ("后端服务监听哪个端口", "后端用的是什么端口", True),
    ("知识库用的是什么 Embedding 模型", "向量化用的是哪个模型", True),
]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def embed_all(client, texts: list[str]) -> list[list[float]]:
    """批量向量化。分批是为了避免单次请求体过大。"""
    vectors: list[list[float]] = []
    batch = 16
    for start in range(0, len(texts), batch):
        vectors.extend(client.embed(texts[start:start + batch]))
    return vectors


def is_cacheable(case: dict) -> bool:
    """这条用例的答案会不会被写进缓存。

    服务端的规则是：用过 `get_current_time` / `web_search` 的答案一律不缓存
    （结果随时间变化），带图片的也不缓存。所以**风险集合应当只包含
    真正会被缓存的那些问题**——否则会把"时间类问题"这种天然高相似、
    却根本不会进缓存的配对算成误命中，白白把阈值推高到没收益的程度。
    """
    tools = set(case.get("expect_tools") or [])
    if tools & {"get_current_time", "web_search"}:
        return False
    if case.get("requires_network"):
        return False
    return True


def nearest_other(vectors, cacheable: list[bool],
                  numbers: list[tuple[str, ...]]) -> list[tuple[float, int]]:
    """对每个问题，找出与它最相似的**其它**问题的相似度。

    比对范围与服务端保持一致，只保留真正可能命中的配对：
    - 双方都可缓存（答案不随时间变化）
    - 数字集合相同（换了参数的同类问题答案必然不同）
    """
    result = []
    for i, vi in enumerate(vectors):
        if not cacheable[i]:
            result.append((0.0, -1))
            continue
        best, best_j = 0.0, -1
        for j, vj in enumerate(vectors):
            if i == j or not cacheable[j]:
                continue
            if numbers[i] != numbers[j]:
                continue
            score = cosine(vi, vj)
            if score > best:
                best, best_j = score, j
        result.append((best, best_j))
    return result


def evaluate(candidates, false_hit_scores, paraphrase_scores) -> list[dict]:
    """对每个候选阈值，统计误命中数与覆盖的同义改写数。"""
    rows = []
    for threshold in candidates:
        false_hits = sum(1 for s in false_hit_scores if s >= threshold)
        covered = sum(1 for s in paraphrase_scores if s >= threshold)
        rows.append({
            "threshold": threshold,
            "false_hits": false_hits,
            "paraphrases_covered": covered,
            "paraphrase_coverage": round(covered / len(paraphrase_scores), 4)
            if paraphrase_scores else 0.0,
        })
    return rows


def main():
    parser = argparse.ArgumentParser(description="标定语义缓存的相似度阈值")
    parser.add_argument("--threshold", type=float, default=None,
                        help="指定阈值；不指定时按候选区间扫描")
    parser.add_argument("--limit", type=int, default=None, help="只取前 N 条用例")
    args = parser.parse_args()

    from agent.rag.embeddings import EmbeddingClient

    cases = load_dataset()
    if args.limit:
        cases = cases[:args.limit]

    cases = [c for c in cases if (c.get("input") or c.get("question") or "").strip()]
    questions = [c.get("input") or c.get("question") for c in cases]
    cacheable = [is_cacheable(c) for c in cases]
    numbers = [number_signature(q) for q in questions]

    print(f"评测集问题数：{len(questions)}")
    print(f"其中答案可被缓存的：{sum(cacheable)}"
          f"（其余涉实时信息，服务端本就不缓存）")

    client = EmbeddingClient()
    print("向量化中...")
    vectors = embed_all(client, questions)

    # ---- 不同问题之间的相似度（误命中风险）----
    # 只在"可缓存"的问题之间比较：不可缓存的答案不会进缓存，
    # 它们之间再相似也不会造成误命中。
    nearest = nearest_other(vectors, cacheable, numbers)
    false_hit_scores = [score for score, _ in nearest if score > 0]
    max_other = max(false_hit_scores)
    mean_other = statistics.mean(false_hit_scores)

    print("\n=== 可缓存问题之间的相似度（真正的误命中风险）===")
    print(f"最大：{max_other:.4f}   平均：{mean_other:.4f}")
    ranked = sorted(
        ((s, i) for i, (s, _) in enumerate(nearest)), reverse=True
    )[:5]
    print("\n最相近的几组不同问题（误命中风险最高的地方）：")
    for score, i in ranked:
        _, j = nearest[i]
        print(f"  {score:.4f}  「{questions[i][:36]}」 ↔ 「{questions[j][:36]}」")

    # ---- 同义改写的相似度（应当命中）----
    pairs_text = [text for a, b, _ in PARAPHRASE_PAIRS for text in (a, b)]
    pair_vectors = embed_all(client, pairs_text)
    paraphrase_scores = [
        cosine(pair_vectors[i * 2], pair_vectors[i * 2 + 1])
        for i in range(len(PARAPHRASE_PAIRS))
    ]
    # 覆盖率只在"答案可缓存"的改写对上统计
    cacheable_para = [s for s, (_, _, ok) in zip(paraphrase_scores, PARAPHRASE_PAIRS) if ok]
    min_para = min(cacheable_para)

    print("\n=== 同义改写之间的相似度 ===")
    print(f"可缓存改写对：{len(cacheable_para)}/{len(PARAPHRASE_PAIRS)}")
    print(f"最小：{min_para:.4f}   平均：{statistics.mean(cacheable_para):.4f}")
    for (a, b, ok), score in zip(PARAPHRASE_PAIRS, paraphrase_scores):
        mark = "  " if ok else "×"
        print(f" {mark} {score:.4f}  「{a[:30]}」 ↔ 「{b[:30]}」")

    # ---- 扫描候选阈值 ----
    candidates = [0.80, 0.85, 0.88, 0.90, 0.92, 0.95]
    rows = evaluate(candidates, false_hit_scores, cacheable_para)

    print("\n=== 阈值扫描（false_hits 必须保持为 0）===")
    print(f"{'阈值':>6} {'误命中数':>8} {'覆盖改写':>9} {'覆盖率':>8}")
    for row in rows:
        print(f"{row['threshold']:>6.2f} {row['false_hits']:>8} "
              f"{row['paraphrases_covered']:>9} {row['paraphrase_coverage']:>8.0%}")

    safe = [r for r in rows if r["false_hits"] == 0]
    if safe:
        # 两级排序：先取覆盖率最高的；覆盖率相同时取**阈值最高**的那个。
        # 后者的理由是安全余量——本数据集没覆盖到的"相似但不同"的配对
        # 可能比已观测到的最大值更高，余量越大越抗未知样本。
        best_coverage = max(r["paraphrase_coverage"] for r in safe)
        recommended = max(
            r["threshold"] for r in safe
            if r["paraphrase_coverage"] == best_coverage
        )
        print(f"\n安全余量：{recommended:.2f} - {max_other:.4f} = {recommended - max_other:.4f}")
    else:
        recommended = 0.99

    print(f"\n建议阈值：{recommended:.2f}")
    print(f"（区间：不同问题最大 {max_other:.4f} < 阈值 < 同义改写最小 {min_para:.4f}）")

    chosen = args.threshold if args.threshold is not None else recommended
    final_false = sum(1 for s in false_hit_scores if s >= chosen)
    print(f"在阈值 {chosen:.2f} 下，{len(questions)} 条评测问题中会误命中的条数：{final_false}")

    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "questions": len(questions),
        "cacheable_questions": sum(cacheable),
        "distinct": {
            "max_similarity": round(max_other, 4),
            "mean_similarity": round(mean_other, 4),
        },
        "paraphrase": {
            "min_similarity": round(min_para, 4),
            "mean_similarity": round(statistics.mean(paraphrase_scores), 4),
            "pairs": [
                {"a": a, "b": b, "score": round(s, 4), "cacheable": ok}
                for (a, b, ok), s in zip(PARAPHRASE_PAIRS, paraphrase_scores)
            ],
        },
        "threshold_scan": rows,
        "recommended_threshold": recommended,
        "chosen_threshold": chosen,
        "false_hits_at_chosen": final_false,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / "cache_calibration.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{path}")


if __name__ == "__main__":
    main()
