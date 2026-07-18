# AI Stock Picker

`ai-stock-picker` 接收已经生成的候选池，调用大语言模型重新排序，并输出经过校验的 JSON 结果。

当前支持：

- A 股正式选择使用 DeepSeek
- 美股使用 Gemini
- A 股 `bounded_ranking_v2` 研究 shadow 可使用 DeepSeek 或 OpenAI Responses API

模型只能从候选池中选择股票。股票代码、名称和主题均以输入数据为准。

本项目不负责行情采集、候选池生成、回测、消息推送或自动下单。

## 安装

需要 Python 3.10 至 3.12 和 `uv`。

```bash
uv sync --locked --group dev
uv run aipick --help
```

## 先运行 dry-run

dry-run 会校验候选池并生成 prompt 摘要，不访问模型、不读取凭据，也不写入结果文件。

A 股示例：

```bash
uv run aipick cn pick \
  --candidates "$PWD/examples/cn_candidates.json" \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

美股示例：

```bash
uv run aipick us pick \
  --candidates "$PWD/examples/us_candidates.json" \
  --as-of 2026-07-15 \
  --top-n 2 \
  --style quality \
  --dry-run
```

## 正式运行

A 股命令只读取 `DEEPSEEK_API_KEY`：

```bash
export DEEPSEEK_API_KEY='你的密钥'
uv run aipick cn pick \
  --candidates /absolute/path/cn_candidates.json \
  --output /absolute/path/cn_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-flash \
  --thinking disabled \
  --max-tokens 8192
```

A 股默认使用 `deepseek-v4-flash`，并显式关闭推理模式。开启推理模式时可以选择
`high` 或 `max`，此时请求不会发送 `temperature`。`max_tokens` 必须在 1 至 65,536
之间。

```bash
uv run aipick cn pick \
  --candidates /absolute/path/cn_candidates.json \
  --output /absolute/path/cn_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-pro \
  --thinking enabled \
  --reasoning-effort max \
  --max-tokens 32768
```

需要批量回放时，先用 `pick-plan` 冻结候选池、Prompt、展示顺序、模型和推理参数。
该命令不读取凭据，也不会访问网络。生成的 `plan.json` 可交给 `trial` 执行，运行时不能
覆盖已经冻结的模型或推理参数。匿名对照可以同时传入完整的股票代码映射和名称映射，
冻结后的完整 Prompt 不得出现真实代码或名称。完整示例见
[证据归档与稳定性试验](docs/evidence-and-stability.md)。

## bounded v2 shadow

`shadow-day` 读取冻结的 `bounded_ranking_v2 / 2026-07-17.7` 计划，在收盘后对一个
provider/model 固定执行三次。至少两次通过排序合同才生成共识；每次 repetition 以及
consensus 都先在隔离 staging 完整落盘，再原子发布为 complete 或 tombstone 终态；已有
目录不会覆盖。artifact 内嵌相对路径 candidate snapshot，不复制原始绝对路径。OpenAI
路径只读取 `OPENAI_API_KEY`，使用 Responses API Structured Outputs，并固定
`store=false`。

```bash
export OPENAI_API_KEY='你的密钥'
uv run aipick cn shadow-day \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id bounded-v2-shadow \
  --signal-date 2026-07-17 \
  --output-root /absolute/path/shadow \
  --provider openai \
  --model gpt-model-snapshot
```

进程中断导致 repetition 缺失时，使用无网络 watchdog 将缺失单元写为 tombstone：

```bash
uv run aipick cn shadow-watchdog \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id bounded-v2-shadow \
  --signal-date 2026-07-17 \
  --output-root /absolute/path/shadow \
  --provider openai \
  --model gpt-model-snapshot
```

下游不需要复制 owner schema。使用 `contract-info` 获取带摘要的机器合同，并通过 owner
CLI 离线校验 artifact：

```bash
uv run aipick cn contract-info
uv run aipick cn contract-info --json-schema
uv run aipick cn validate-shadow-day --day-dir /absolute/path/shadow/day
uv run aipick cn validate-shadow-campaign --campaign-root /absolute/path/shadow/campaign
```

美股命令只读取 `GEMINI_API_KEY`：

```bash
export GEMINI_API_KEY='你的密钥'
uv run aipick us pick \
  --candidates /absolute/path/us_candidates.json \
  --output /absolute/path/us_selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style quality
```

跨仓调用可以改传 `--credential-file /absolute/path/api_keys.json`。文件必须由当前用户
拥有、权限精确为 `0600`、不超过 128 KiB。推荐 JSON 格式如下。旧的 UTF-8
`KEY=value` 行格式继续兼容。

```json
{
  "ai_stock_picker": {
    "deepseek": {"api_key": "YOUR_DEEPSEEK_API_KEY"},
    "gemini": {"api_key": "YOUR_GEMINI_API_KEY"}
  }
}
```

解析器不调用 shell 或展开变量，只读取当前 provider 的专属 key。JSON 重复字段、错误
类型和空 key 都会失败。未传 `--credential-file` 时才读取进程环境变量。

正式运行会同时生成结果文件和 append-only 证据目录。未传 `--evidence-dir` 时，证据目录为
`<output>.evidence`。两者都拒绝覆盖已有内容。

证据目录保存候选池原文件、完整数值排名、精确 prompt、脱敏后的 HTTP 请求信息、请求
正文、模型服务原始响应、请求模型别名、响应实际模型、模型正文、选择结果和逐文件哈希。
凭据不会写入证据目录。HTTP 调用成功但响应格式无效时，原始响应会保存为拒绝证据，结果
文件不会生成。

证据清单分别记录传输、排序和发布三层合同。模型返回的股票顺序有效，但展示文案未通过
校验时，证据仍保持 `rejected`，并保存只含股票顺序的 `ranking_diagnostic.json`。
该文件用于研究诊断，不会替代正式的 `selection.json`。

`reasoning` 和 `risk_note` 是仅基于候选字段的 AI 解读，未经独立事实核验，
不应包装成已核验事实或投资建议。每个句子可以使用获批的中英文自然标签引用候选字段，
无需向客户暴露 snake_case 字段名。

## 详细文档

- [文档导航](docs/README.md)
- [输入格式](docs/input-formats.md)
- [输出格式](docs/output-artifact.md)
- [证据归档与稳定性试验](docs/evidence-and-stability.md)
- [时间与证据边界](docs/trust-boundaries.md)
- [项目架构](docs/architecture.md)
- [开发与检查](docs/development.md)
- [示例文件说明](examples/README.md)

## 本地检查

```bash
uv run python scripts/dev/check.py
```

该命令依次检查依赖锁、Ruff、格式、ty、测试覆盖率、维护性指标和构建结果。

本项目输出用于研究和流程衔接，不构成投资建议。
