# Agent 评测体系

非确定性的 LLM 系统如果没有评测，优化就只能靠感觉。本目录提供一套可复现、
可扩展的离线评测框架，用于量化 Agent 的任务成功率、工具调用准确率、延迟与成本。

## 设计原则

**分层判定。** 一次调用是否通过，取决于以下检查是否全部成立：

1. **工具调用是否正确** —— 该调的调了、不该调的没乱调
2. **最终答案是否正确** —— 规则匹配优先，开放式题目交给 LLM-as-judge
3. **引用是否标注**（仅 `require_citation: true` 的用例）—— RAG 场景下没有引用
   就无法核验回答是否忠实于原文

分开统计是有意的：答案碰巧答对但工具没调（模型在心算），属于"结果正确、
过程不可靠"，在生产环境里一旦数值变大就会出错。这类用例必须暴露出来，
不能被整体准确率掩盖。

**规则优先于 LLM 判定。** 数值、格式类断言用确定性规则，避免"让模型给自己
打分"引入的系统性偏差，也让结果可复现。只有语义类判断才动用 LLM judge。

**失败要能定位。** 每条用例都记录实际调用了哪些工具、模型的完整回答、
失败原因、延迟与 token 消耗，能直接看出问题出在规划、工具还是生成阶段。

## 数据集

`dataset.jsonl`，每行一条用例：

```json
{
  "id": "math_001",
  "category": "math_direct",
  "input": "帮我算一下 123 * 456 等于多少",
  "turns": ["...", "..."],
  "expect_tools": ["calculate"],
  "tool_match": "any",
  "judge": {"type": "exact_number", "expected": 56088},
  "requires_network": false,
  "notes": "基础乘法，验证端到端工具链路"
}
```

| 字段 | 说明 |
| --- | --- |
| `turns` | 可选。多轮用例，按顺序发送，只对最后一轮判定 |
| `expect_tools` | 期望调用的工具名列表，空数组表示不该调用 |
| `tool_match` | `any` 命中之一 / `exact` 集合一致 / `none` 禁止调用 / `optional` 不校验 |
| `judge.type` | 见下表 |
| `requires_network` | 是否需要联网检索，可用 `--skip-network` 跳过 |
| `require_citation` | 是否要求回答带 `[n]` 形式的引用标注（RAG 用例使用） |

### judge 类型

| 类型 | 用途 | 备注 |
| --- | --- | --- |
| `exact_number` | 数值答案 | 支持相对容差（默认 1%），自动处理千分位 |
| `contains` | 关键词命中 | 大小写不敏感 |
| `not_contains` | 确认危险内容没有出现 | 注意无法区分"复述攻击载荷"和"执行结果" |
| `regex` | 格式校验 | 如日期写法 |
| `llm_judge` | 开放式语义判定 | 依据 `rubric` 打分 |
| `refusal` | 安全拒绝判定 | 关键词兜底 + LLM 复核语义 |

### 数据集规模分类

| 类别 | 条数 | 考察点 |
| --- | --- | --- |
| `math_direct` | 20 | 单步计算的工具调用链路 |
| `math_multi_step` | 12 | 需自行构造复合表达式 |
| `time_query` | 12 | 是否凭记忆编造时间（含星期、年份、24 小时制） |
| `realtime_info` | 8 | 实时信息是否检索（需联网） |
| `no_tool_needed` | 15 | 是否过度调用工具 |
| `multi_turn` | 15 | 多轮上下文与指代消解 |
| `multi_tool` | 11 | 一次请求需要多个工具协作 |
| `prompt_injection` | 20 | 注入攻击、凭据窃取、越权索取 |
| `edge_case` | 20 | 除零、非法输入、单位换算、精度 |
| `rag_qa` | 25 | 知识库检索、引用标注、未命中时是否编造 |

合计 **158 条**，其中 9 条需要联网检索（`--skip-network` 时跳过）。

### 静态校验：写错的用例在加载阶段就会被拦下

数据集写错会让评测结果**完全失真且极其隐蔽**——曾因 `expect_tools: []` 配
`tool_match: "any"`（空集求交必然为空），整批安全用例被误判失败，看起来像
"模型安全能力不足"，实际是配置错误。所以校验是**代码化的**（`evals/dataset.py`
的 `validate_case`），加载时执行，不通过的行会被跳过并打 `[warn]`。

| 规则 | 拦截什么 |
| --- | --- |
| `id` 非空且唯一 | 缺 id 或 id 重复（重复会导致后写的用例静默顶掉前面的） |
| `input` 非空 | 空问题会产出无意义的评测结果 |
| `expect_tools` 为空时 `tool_match` 不能是 `any` | 空集相交必然判负；应改用 `none`（禁止调用）或 `optional`（不校验） |
| `tool_match` ∈ {any, none, exact, optional} | 拼写错误被当成"未校验" |
| `judge.type` 必须是已注册的判定器 | 未知类型会被静默跳过，等于该用例没跑 |

检索集（`retrieval_dataset.jsonl`）单独校验三项：`id` 唯一、必须有 `query`、
必须有 `gold_keywords`。

这些规则本身又被 `tests/test_dataset.py` 锁住（12 条测试），
包括"所有用例都能通过校验""id 不重复""类别齐全""RAG 用例必须要求引用"
——所以**校验规则自身也在 CI 里**，不会悄悄失效。

### 新增用例的注意事项

1. `expect_tools: []` 只能配 `none` 或 `optional`（安全类用例常用 `optional`：
   模型直接拒绝、或调用后被拦截，都算正确）
2. 数值判据优先用 `exact_number`（默认 1% 相对容差，会自动处理千分位），
   别用 `contains` 匹配字符串形式的数字
3. `realtime_info` 类必须 `requires_network: true` + `llm_judge`，
    rubric 里要写明"不得凭记忆编造精确数值""失败时应如实说明"
4. `rag_qa` 类应带 `require_citation: true`（负样本除外），否则引用溯源形同虚设
5. 多轮用例用 `turns` 数组，只对**最后一轮**判定，`input` 填最后一轮的问题

## 两个评测模块的分工

| 模块 | 测什么 | 数据集 |
| --- | --- | --- |
| `run_eval.py` | 端到端答案：用户拿到的回答对不对、工具调没调、引用标没标 | `dataset.jsonl`（148 条） |
| `retrieval_eval.py` | 只测检索环节：该召回的内容有没有召回到、生成是否忠实 | `retrieval_dataset.jsonl`（36 条） |

分开测的原因：端到端失败时，如果分不清是"检索没召回"还是"生成不忠实"，
只能靠猜去改。分开后可以直接定位：Recall 低说明检索有问题，
Recall 高但答案错说明是生成环节的问题。

检索评测的指标包括 Recall@1/3/5、MRR、Precision@k，
以及**精排前后的对比**（体现 cross-encoder 的实际增益），
可选跑忠实度（生成是否编造了资料外的信息）。

## 运行

```bash
python -m evals.run_eval                        # 全量（含需联网用例）
python -m evals.run_eval --skip-network         # 跳过联网用例，离线可跑
python -m evals.run_eval --category prompt_injection
python -m evals.run_eval --limit 10 --concurrency 2
python -m evals.run_eval --tag my-experiment
python -m evals.run_eval --repeat 3          # 建议：正式结论至少跑 3 轮
```

检索质量单独评测：

```bash
python -m evals.retrieval_eval                 # Recall / MRR / Precision / 精排增益
python -m evals.retrieval_eval --faithfulness  # 追加忠实度（需调用模型生成）
python -m evals.retrieval_eval --limit 10      # 只跑前 N 条
```

## 为什么必须有 `--repeat`

LLM 输出有采样随机性。同一个 commit 连续跑四轮，得到的失败集合完全不同：

| 轮次 | 通过率 | 失败用例 |
| --- | --- | --- |
| baseline-v1 | 96.2% | edge_003, edge_007 |
| prompt-v2 | 98.1% | sec_003 |
| prompt-v3 | 98.1% | math_multi_001 |
| tools-v4 | 94.3% | edge_003, sec_007, sec_008 |

如果只看单轮，会误以为 prompt-v3 比 baseline-v1 差 2 个点，实际上换掉的只是随机失败的用例。
`--repeat 3`（或更多）后，报告会额外给出：

- **平均通过率** 与各轮**波动区间**
- **稳定通过率**：N 轮全部通过的用例占比，这是最有参考价值的质量指标
- **抖动用例清单**：结果不稳定的用例，说明这些题目处于模型能力边界或判定 ambiguous
- **从未通过的用例**：真正的能力短板，优先修这些

对比两次评测时应优先看稳定通过率，而不是单轮通过率。

开启 LangSmith 后，每次评测的 trace 会自动带上 `eval`、`{tag}`、`{category}` 标签，
可在 LangSmith 控制台里筛选回放：

```bash
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=<your-key>
```

### 对比两次结果

```bash
python -m evals.compare evals/reports/baseline-v1.json evals/reports/report_xxx.json
python -m evals.compare A.json B.json --downgrade-only   # 有回归就以非零码退出，可接 CI
```

## 产物

每次运行会在 `evals/reports/` 下生成：

- `report_<时间戳>.json` —— 逐条完整结果
- `report_<时间戳>.md` —— 汇总表格，可直接贴进文档
- `latest.json` / `latest.md` —— 最近一次结果

## 已知局限

- 当前 58 条用例规模偏小，单个随机波动影响较大，扩展到 150+ 条后结论才更稳健。
- 即使多轮取平均，`llm_judge` 本身的判定仍带非确定性，抖动用例里有一部分是评分抖动而非能力抖动。
- `llm_judge` 判定本身有非确定性，同一份报告重复评分可能有个别用例翻转。
- 成本估算是按 `agent/pricing.py` 里的 `PRICING` 表计算的静态价格（评测与线上共用同一份），
  实际请以官方最新定价为准，可用环境变量 `PRICE_INPUT` / `PRICE_OUTPUT`
  （旧名 `EVAL_PRICE_INPUT` / `EVAL_PRICE_OUTPUT` 仍兼容）覆盖。
- 评测直接调用 Agent 层，未覆盖 HTTP 接口、鉴权与 Redis 会话链路。

## 踩过的坑

初版 `expect_tools: []` 与 `tool_match: "any"` 组合时，两个空集求交必然为空，
导致 `prompt_injection` 整批被调用判定误杀，表面看起来是模型安全能力不足，
实际是评测配置的错误。现在 `load_dataset` 会在加载时静态校验这类矛盾配置并跳过，
`compare.py` 也专门输出回归清单，避免同类问题再次干扰判断。

RAG 用例上还踩过两个判据本身的坑：

- **字符串匹配过严**：模型回答"基于 AST 白名单求值，不是 eval"，
  但 rubric 要求必须出现"不使用 eval"四个字，被判失败。语义正确的答案
  不该因为措辞不同被判错，这类断言应交给 `llm_judge`。
- **rubric 写得太贪心**：把"说明安全目的"也列为必需项，导致核心事实都答对了
  仍判不通过。**rubric 只应包含核心事实要求**，锦上添花的内容不要写进去。

另外，`rag_003` 最初问"calculate 是用 eval 实现的吗"，模型会把它理解成
"询问系统内部实现"的元问题而**不检索知识库**，直接回答"无法确认"。
这不是缺陷而是真实的模型行为边界——最终把用例改成文档查询式的自然表述。
