# 输出格式

正式运行会生成 `ai_stock_selection` v1 JSON 文件。

输出文件写入前会再次通过 Pydantic strict 校验。目标路径已经存在时，命令会失败，不会覆盖原文件。

## 顶层字段

### 身份字段

- `schema_version`
- `artifact_type`
- `market`

当前值：

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection",
  "market": "CN"
}
```

### 时间字段

- `selection_as_of`
- `candidate_observation_date`
- `candidate_generated_at`
- `data_cutoff`
- `upstream_execution_not_before`
- `generated_at`
- `temporal_status`

`generated_at` 会转换为 UTC。

`temporal_status` 可能为：

- `contemporaneous`
- `retrospective_simulation`

详细语义见 [时间与证据边界](trust-boundaries.md)。

### 模型字段

- `provider`
- `model`
- `prompt_version`
- `style`
- `selection_method`

A 股 provider 固定为 `deepseek`。

美股 provider 固定为 `gemini`。

`selection_method` 当前固定为 `llm_candidate_rerank`。

### 输入与证据字段

- `input_contract`
- `point_in_time_assurance`
- `strict_point_in_time`
- `eligible_as_oos_evidence`
- `evidence_limitations`
- `input_count`
- `requested_top_n`

当前所有结果固定包含：

```json
{
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false
}
```

这些字段用于防止结果被误解为严格时点证明或正式样本外证据。

## Lineage

`lineage` 记录本次结果所依赖内容的 SHA-256：

- `candidate_path`
- `input_sha256`
- `candidate_symbols_sha256`
- `prompt_sha256`
- `response_sha256`

哈希可以用于检查内容是否变化。

哈希不能证明内容在某个历史时间已经存在，也不能代替外部可信时间戳。

## Picks

`picks` 数量必须与 `requested_top_n` 完全一致。

每个结果包含：

- `rank`
- `symbol`
- `name`
- `topic`
- `confidence_score`
- `reasoning`
- `risk_note`

其中模型只负责返回：

- `symbol`
- `confidence_score`
- `reasoning`
- `risk_note`

`name` 和 `topic` 由程序从候选池回填。

程序还会检查：

- 股票代码来自候选池
- 股票代码不重复
- 排名从 1 开始连续递增
- `confidence_score` 是 1 至 10 的整数
- 模型没有返回额外字段
- A 股解释和风险说明包含中文
- 美股解释和风险说明使用英文

## 简化示例

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "ai_stock_selection",
  "market": "CN",
  "selection_as_of": "2026-07-15",
  "candidate_observation_date": "2026-07-14",
  "candidate_generated_at": "2026-07-14T22:00:00Z",
  "data_cutoff": "2026-07-14",
  "upstream_execution_not_before": "next_trading_session",
  "generated_at": "2026-07-15T02:00:00Z",
  "provider": "deepseek",
  "model": "deepseek-chat",
  "prompt_version": "2026-07-15.2",
  "style": "momentum",
  "input_contract": "hot_sector_candidate_universe_v1",
  "temporal_status": "contemporaneous",
  "point_in_time_assurance": "signal_date_only",
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false,
  "evidence_limitations": [
    "rotation_publisher_receipt_unavailable",
    "candidate_artifact_does_not_establish_out_of_sample_validity"
  ],
  "input_count": 20,
  "requested_top_n": 1,
  "selection_method": "llm_candidate_rerank",
  "lineage": {
    "candidate_path": "/path/to/candidates.json",
    "input_sha256": "省略",
    "candidate_symbols_sha256": "省略",
    "prompt_sha256": "省略",
    "response_sha256": "省略"
  },
  "picks": [
    {
      "rank": 1,
      "symbol": "002371.SZ",
      "name": "北方华创",
      "topic": "半导体国产替代",
      "confidence_score": 8,
      "reasoning": "候选特征中的量价与主题信号支持该排序。",
      "risk_note": "主要风险来自波动和主题集中。"
    }
  ]
}
```

示例中的哈希经过省略。真实结果使用 64 位小写十六进制 SHA-256。
