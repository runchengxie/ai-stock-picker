# 输出格式

正式结果使用 `ai_stock_selection` v2。

主要字段包括：

- 市场、选择日期、候选观测日期和生成时间
- provider、provider API、model、temperature
- prompt 版本、排序风格和输出语言
- 输入契约、时点状态和证据限制
- `generation_trace`
- 排名连续且数量精确的 `picks`

## generation_trace

`generation_trace` 表示生成追踪信息：

```json
{
  "candidate_source": "candidates.json",
  "input_sha256": "...",
  "candidate_symbols_sha256": "...",
  "prompt_sha256": "...",
  "response_sha256": "..."
}
```

它可以判断本次结果使用了哪份逻辑输入，以及输入、候选代码集合、prompt 和模型响应内容是否一致。

`candidate_source` 只保存文件名，不保存本地绝对路径。

这些哈希是内容指纹，不是外部可信时间戳，也不能证明上游数据真实可靠。

## picks

模型只能返回：

- `symbol`
- `confidence_score`
- `reasoning`
- `risk_note`

最终 `name` 和 `topic` 由程序从候选 manifest 回填。

以下情况会拒绝发布：

- 数量和 `top_n` 不一致
- 重复股票
- 候选池外股票
- 额外字段
- 非整数置信度
- `zh-CN` 输出缺少 CJK 汉字
- schema 交叉校验失败

结果文件采用原子、不可覆盖写入。两个并发 writer 只有一个可以成功。
