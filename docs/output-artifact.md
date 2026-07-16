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

保存 artifact 后可以用同一份候选快照做严格复验：

```bash
uv run aipick cn validate \
  --selection outputs/cn-selection.json \
  --candidates /absolute/path/candidates.json
```

命令会重新读取候选快照并核对路径、输入哈希、代码集合哈希、日期、数量、候选元数据、
证据限制、入选成员、名称、主题和每条展示文案。当前 prompt 会确定性重建并核对
`prompt_sha256`，`validation_profile` 为 `current_full`。

兼容版本 `2026-07-15.2` 和 `2026-07-15.3` 使用 `legacy_read_only`。这些版本保留输入、
成员和文案安全检查，不复算已经变化的 prompt，也不会改写旧结果。

传入 `--evidence-dir` 后，命令还会核对证据目录中的原始响应、精确 prompt、选择结果和
逐文件哈希，并报告 `response_sha256_verification=byte_exact_evidence`。旧结果缺少证据
目录时，只能检查响应哈希的格式。

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
- 每个句子都以内部字段名或获批的中英文客户标签引用该候选实际存在的字段
- 文本不披露实际 provider/model 身份或结构化系统元数据，也不包含 URL/secret、买卖或
  持有指令、目标价或保证收益

## Customer commentary 边界

`reasoning` 与 `risk_note` 只用于表达基于候选字段的 AI interpretation，未经独立事实
核验。持久化 artifact schema 不为此增加字段。面向客户的 consumer 必须
固定展示该标签，不能将模型文本包装成已核验事实或投资建议。

prompt 只允许模型引用候选对象中的字段、`source_topics` 和 `source_concepts`。上游
`risk_score` 会在进入 prompt 前投影成 `intraday_stability_score`，语义固定为
`higher = more stable`。高值不得解释为风险更高。当前 prompt 版本为
`2026-07-16.4`。该版本移除了带真实股票代码的响应示例，每个候选只渲染一份顶层
`score`。reader 兼容读取 `2026-07-15.2` 和 `2026-07-15.3`，正式 writer 只发布当前
版本。预注册稳定性试验使用隔离的 legacy v3 构建器，继续保留旧版示例和重复 `score`。

创建 artifact 时还会进行 fail-closed 校验：

- 每个句子至少引用一个实际存在的候选字段或其获批自然语言标签
- 引用 `source_topics`、`source_concepts`、`topic`、`name`、`symbol`、`sector`、
  `industry` 或 `confidence_label` 时，句中必须原样包含该候选字段的实际值
- 拒绝不属于候选字段白名单的显式字段引用
- Unicode 规范化后拒绝 Cyrillic/Greek confusable、域名、邮件、IP 地址、provider/model、
  凭据和 secret
- 拒绝交易指令、目标价、保证收益、`风险分`、稳定性语义颠倒以及常见外部或未来事实
  表述。

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
  "prompt_version": "2026-07-16.4",
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
      "reasoning": "综合候选评分与热点主题中的半导体国产替代支持相对排序。",
      "risk_note": "仅依据综合候选评分与热点主题中的半导体国产替代，风险解读仍有信息边界。"
    }
  ]
}
```

示例中的哈希经过省略。真实结果使用 64 位小写十六进制 SHA-256。
