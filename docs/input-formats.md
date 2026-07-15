# 输入格式

`aipick` 接受 JSON manifest，也兼容 UTF-8 CSV。

推荐使用 JSON。JSON 可以记录生成时间、观测日期和数据截点。CSV 缺少这些信息，只适合探索和旧数据迁移。

## 通用限制

所有输入都会检查：

- 文件必须存在
- 文件大小不能超过 10 MB
- 候选数量不能超过 1000
- 候选池不能为空
- 股票代码必须符合市场格式
- 股票代码不能重复
- 分数必须是有限数值
- 名称、主题和特征字符串不能超过长度限制

`--as-of` 表示本次选择信号日期。候选数据的观测日期可以早于该日期，不能晚于该日期。

## A 股 JSON

A 股优先使用 `hot_sector_candidate_universe` v1 契约。

仓库示例：

- [`../examples/cn_candidates.json`](../examples/cn_candidates.json)

### 契约标识

以下字段必须完全匹配：

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "hot_sector_candidate_universe",
  "market": "CN"
}
```

### 日期与时间

以下日期字段必须指向同一个观测日：

- `date`
- `date_int`
- `observation_date`
- `data_cutoff`

`generated_at` 必须是带 UTC offset 的 ISO 8601 时间。

同日生成时，上海市场时间不能早于 16:00。观测日之后生成的候选池会记录相应证据限制。

还需要满足：

```json
{
  "data_cutoff_semantics": "end_of_day",
  "execution_not_before": "next_trading_session",
  "future_data_included": false
}
```

项目只记录 `execution_not_before`。项目没有交易所日历，不会自行验证实际下一交易日。

### 候选字段

每个候选至少需要：

- `ts_code`
- `name`
- `score`
- `relevance`
- `source_topics`
- `source_concepts`

示例：

```json
{
  "ts_code": "002371.SZ",
  "name": "北方华创",
  "score": 1.25,
  "relevance": 0.92,
  "source_topics": ["半导体国产替代"],
  "source_concepts": ["半导体设备"]
}
```

`score` 必须是有限数值。

`relevance` 必须位于 0 至 1 之间。

`source_topics` 和 `source_concepts` 必须是字符串数组，数组中的字符串不能为空。

### Provenance 与 evidence

A 股 v1 契约还会检查：

- `provenance.timezone`
- `provenance.observation_date`
- `provenance.data_cutoff`
- `provenance.rotation`
- `evidence.temporal_context`
- `evidence.limitations`
- `quality_report`
- `outcome_report`

生成阶段的 `quality_report` 和 `outcome_report` 必须保持 deferred 状态。候选生成阶段不能写入未来表现。

完整字段可直接参考仓库中的 A 股示例。

## 美股 JSON

美股当前使用通用 JSON manifest。

仓库示例：

- [`../examples/us_candidates.json`](../examples/us_candidates.json)

顶层至少需要：

- `generated_at`
- `date`、`observation_date` 或 `as_of`
- `universe_size`
- `candidates`

候选至少需要：

- `ticker` 或 `symbol`
- `company_name` 或 `name`
- `score`

主题可以来自：

- `sector`
- `industry`
- `topic`

示例：

```json
{
  "date": "2026-07-14",
  "generated_at": "2026-07-15T08:30:00-04:00",
  "data_cutoff": "2026-07-14",
  "universe_size": 1,
  "candidates": [
    {
      "ticker": "AAPL",
      "company_name": "Apple Inc.",
      "score": 7.5,
      "sector": "Technology"
    }
  ]
}
```

通用 JSON 没有受支持的版本化契约，因此 `point_in_time_assurance` 会标记为 `unverified`。

## Legacy CSV

CSV 必须使用 UTF-8 编码。

A 股需要：

- `ts_code` 或 `symbol`
- `name`
- `score` 或可转换为数值的 `relevance`

美股需要：

- `ticker` 或 `symbol`
- `company_name` 或 `name`
- `score` 或可转换为数值的 `relevance`

可选日期字段：

- `trade_date`
- `date`
- `as_of`

CSV 可以使用 JSON 数组或 Python 列表文本表示主题。该兼容能力主要服务旧文件，不建议用于新流程。

CSV 没有 manifest 生成时间和可信数据截点，因此结果始终标记为 `unverified`。

## 常见错误

### `top_n exceeds candidate count`

`--top-n` 大于候选数量。请减少数量或提供更大的候选池。

### `manifest observation date is after selection --as-of`

候选观测日在选择信号日期之后。请检查 `--as-of` 和输入文件日期。

### `candidate symbols must be unique`

候选池包含重复股票代码。

### `manifest generated_at must include an explicit UTC offset`

`generated_at` 缺少时区信息。请使用类似 `2026-07-15T08:30:00+08:00` 的格式。
