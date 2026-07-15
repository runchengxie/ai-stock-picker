# 时间与证据边界

## 时间字段

- `candidate_observation_date`：候选数据对应的观测日
- `data_cutoff`：候选生成允许使用的数据截点
- `candidate_generated_at`：候选 manifest 的生成时间
- `selection_as_of`：本次模型重排对应的信号日期
- `generated_at`：选股 artifact 的生成时间

时间比较使用 manifest 声明的市场时区。

## temporal_status

当选股结果在 `selection_as_of` 对应市场日期生成时，状态为 `contemporaneous`。

晚于该市场日期生成时，状态为 `retrospective_simulation`，并增加对应 limitation。

## point_in_time_assurance

- `signal_date_only`：仅适用于通过完整校验的热题材 v1
- `unverified`：适用于通用候选池 v1

这两个值都不代表严格 point-in-time 证明。

## 固定限制

所有结果固定包含：

```json
{
  "strict_point_in_time": false,
  "eligible_as_oos_evidence": false
}
```

内容哈希只能识别内容，不能证明文件在某个历史时间已经存在。

本项目没有交易所日历和成交系统，因此不会验证下一交易日、开盘可得性、成交价格或实际可成交性。
