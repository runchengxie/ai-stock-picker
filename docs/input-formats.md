# 输入格式

核心命令 `aipick pick` 只接受版本化 JSON manifest。

市场由 manifest 的 `market` 字段声明，当前支持 `CN` 和 `US`。

## 通用候选池 v1

```json
{
  "schema_version": "1.0.0",
  "artifact_type": "stock_candidate_universe",
  "market": "US",
  "observation_date": "2026-07-14",
  "generated_at": "2026-07-15T08:30:00-04:00",
  "data_cutoff": "2026-07-14",
  "universe_size": 2,
  "candidates": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "score": 9.0,
      "topic": "Technology",
      "features": {
        "quality": 0.9
      }
    }
  ]
}
```

每个候选必须包含：

- `symbol`
- `name`
- `score`

可选字段：

- `topic`
- `features`

通用 v1 可以同时表达 A 股和美股候选。市场只影响股票代码校验和时间判断。

通用 v1 不具备上游发布回执，因此 `point_in_time_assurance` 固定为 `unverified`。

## 热题材候选池 v1

项目继续支持 `hot_sector_candidate_universe` v1。该契约包含更严格的 A 股时点、provenance、rotation 和 evidence 字段。

完整示例见：

- [`examples/cn_candidates.json`](../examples/cn_candidates.json)

它最高只提供 `signal_date_only` assurance，仍然不构成严格时点证明或样本外证据。

## 输入限制

- 文件必须是 UTF-8 JSON object
- 最大 10 MB
- 候选最多 1000 行
- 股票代码必须唯一
- `score` 必须是有限数值
- `generated_at` 必须带 UTC offset
- `data_cutoff` 不能晚于 `observation_date`
- `observation_date` 不能晚于本次 `--as-of`

## legacy CSV

CSV 不再进入核心选股路径。

使用 `aipick migrate-csv` 将旧 CSV 转成通用候选池 v1。迁移命令要求显式提供市场、观测日期、生成时间和数据截点，避免程序替用户猜测时点语义。
