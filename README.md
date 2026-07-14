# AI Stock Picker

`ai-stock-picker` 的发布边界很小：让指定 LLM 只在一份显式提供、已经生成的候选池内
重新排序，并输出严格、可追溯的选股 artifact。模型不能增加候选池外的股票，也不能
决定股票名称或主题。

当前只发布两个命令：

```text
aipick cn pick    # DeepSeek 重排 A 股候选池
aipick us pick    # Gemini 重排美股候选池
```

本仓不生成候选池，不提供消息推送、历史补选、回测或下单入口。

## 安装

支持 Python 3.10–3.12：

```bash
uv sync --group dev
uv run aipick --help
```

wheel 内包含运行 CLI 所需的全部本仓代码。CLI 不读取仓库根目录下的隐式数据或配置，
因此可以从任意工作目录运行。

## 候选池输入

`--candidates`、`--output` 和 `--as-of` 都是必填项。`--as-of` 表示本次选择的
`selection_as_of`，不是候选数据的观测日。常见流程是：

```text
D 日收盘数据完成 → 生成候选池 → D+1 形成 selection signal
```

所以 `candidate_observation_date=2026-06-29`、`selection_as_of=2026-06-30` 是合法
组合；候选观测日只需不晚于选择日。manifest 的 `generated_at` 必须带 UTC offset，
并且正式选择的生成时间不能早于候选 manifest。

A 股优先消费 `hot-sector-screener` 的
`hot_sector_candidate_universe` v1 契约。仓库中的
[`examples/cn_candidates.json`](examples/cn_candidates.json) 与 owner repo 的 canonical
example 完全一致，并同时通过 producer 与 consumer 校验。该契约会严格检查：

- 固定的 schema identity、CN market、相互一致的 observation/cutoff 日期；
- `generated_at` 不早于上海市场观测日 16:00；
- 每行同时包含有限的 `score`、有限且在 `[0, 1]` 内的 `relevance`，以及字符串数组
  `source_topics`、`source_concepts`；
- provenance、rotation receipt 限制、temporal context、OOS disclaimer；
- generation-time 的 `quality_report`、`outcome_report` 必须保持 deferred。

美股可使用通用 JSON manifest，示例见
[`examples/us_candidates.json`](examples/us_candidates.json)。它需要带时区的
`generated_at`、观测日期、`universe_size`，候选行使用 `ticker`、`company_name`、
`score`，并可用 `sector` 或 `industry` 表示主题。

兼容 UTF-8 legacy CSV，但它只适合探索。CSV 需要对应市场的 symbol/name 与数值分数；
可选 `trade_date`、`date` 或 `as_of` 不得晚于选择日。CSV 没有 manifest 生成时间和
可信数据截点，因此 assurance 始终为 `unverified`。

所有输入还会检查大小、行数、symbol 格式和唯一性、有限数值以及候选字符串长度。
通用 JSON 或 CSV 不能通过自报字段升级为受信任的 point-in-time 契约。

## 使用

先 dry-run。它会验证候选池并生成 prompt hash，不访问模型，也不写输出：

```bash
uv run aipick cn pick \
  --candidates "$PWD/examples/cn_candidates.json" \
  --output /tmp/cn-selection.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

正式调用 DeepSeek：

```bash
export DEEPSEEK_API_KEY='...'
uv run aipick cn pick \
  --candidates /absolute/path/candidate_universe.json \
  --output /absolute/path/deepseek-selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style quality
```

调用 Gemini：

```bash
export GEMINI_API_KEY='...'
uv run aipick us pick \
  --candidates /absolute/path/us_candidates.json \
  --output /absolute/path/gemini-selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style growth
```

CN 只读取 `DEEPSEEK_API_KEY`，US 只读取 `GEMINI_API_KEY`。请求使用代码内固定的
provider HTTPS endpoint；Gemini key 放在 `x-goog-api-key` header，不进入 URL。
凭据使用不可转发 header，provider redirect 不会把 key 带到新地址。

输出路径采用 fail-closed 语义：已存在的 artifact 永不覆盖，两个并发 writer 也只有
一个能成功发布。重复运行时应复用已有文件，或选择新的输出路径，而不是改写既有回执。

## 严格模型输出与 lineage

模型只能返回一个 `{"picks": [...]}` JSON 对象。每个 pick 只能包含 `symbol`、
`confidence_score`、`reasoning`、`risk_note`；额外字段、浮点置信度、重复 symbol、
候选池外 symbol，或非精确 `top_n` 数量都会失败。最终 `name` 和 `topic` 只从候选池
回填。

持久化 artifact 是 `ai_stock_selection` v1，主要字段包括：

- `selection_as_of`、`candidate_observation_date`、`candidate_generated_at`、
  `data_cutoff`、UTC `generated_at`；
- `provider`、`model`、`prompt_version`、`style`、`selection_method`；
- `input_contract`、`temporal_status`、`point_in_time_assurance`；
- 输入文件、候选 symbol 集、prompt、原始 provider response 的 SHA-256；
- 连续排名且数量精确的 picks。

输入文件 hash 是内容指纹，不是外部可信时间戳。artifact 固定输出
`strict_point_in_time=false` 和 `eligible_as_oos_evidence=false`。识别出的 hot-sector
v1 最高只标记 `signal_date_only`；通用 JSON 与 CSV 标记 `unverified`，所有限制都写入
`evidence_limitations`。

`temporal_status=contemporaneous` 只表示选择在对应市场的 `selection_as_of` 当日生成，
且未发生候选 manifest 晚于选择时间的因果倒置；它不等于严格 PIT 或 OOS 证据。晚于
选择日运行会标记 `retrospective_simulation`。

上游候选契约中的 `execution_not_before=next_trading_session` 只会原样记录。本仓没有
交易所日历，因此不会声称已经验证实际下一交易日、开盘可得性或成交价格。

## 开发与发布门禁

```bash
make check
uv run pre-commit run --all-files
```

`make check` 会检查 lock freshness、Ruff、格式、strict mypy、默认 pytest、75% branch
coverage、maintainability ratchet，并构建 wheel 与 sdist。CI 还会安装 wheel，并从仓库
外的工作目录对 CN/US CLI 做 dry-run smoke test。
