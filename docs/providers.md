# 模型 provider

市场和模型 provider 相互独立。

候选 manifest 决定：

- 市场
- 股票代码校验规则
- 观测日期和数据截点
- 输入契约及证据限制

运行参数决定：

- provider
- model
- temperature
- 排序风格
- 输出语言

## 内置 provider

### DeepSeek

- provider：`deepseek`
- 默认 model：`deepseek-chat`
- 凭据：`DEEPSEEK_API_KEY`
- API：OpenAI chat-completions 兼容接口

### Gemini

- provider：`gemini`
- 默认 model：`gemini-2.5-flash`
- 凭据：`GEMINI_API_KEY`
- API：Gemini generate-content

内置 provider 使用固定 HTTPS endpoint。用户可以覆盖 model，不能覆盖 endpoint 或凭据变量。

## OpenAI-compatible provider

使用 `openai-compatible` 时必须显式提供：

- `--model`
- `--base-url`
- `--api-key-env`

`--base-url` 必须是完整的 HTTPS chat-completions endpoint，不能包含用户名、密码、query 或 fragment。

凭据通过不可转发 header 发送。HTTP 重定向不会携带 API key。

## 模型热切换

同一份候选 manifest 可以使用不同 provider 或 model 重复 dry-run。正式结果文件不可覆盖，因此每次正式调用应使用独立输出路径。

输出 artifact 会记录：

- provider
- provider API 类型
- model
- temperature
- prompt 版本
- 输出语言

这些信息用于复现生成配置，不代表模型结果必然可重复。
