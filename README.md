# AI Stock Picker

`ai-stock-picker` 接收已经生成的候选池，调用大语言模型重新排序，并输出经过校验的 JSON 结果。

当前支持：

- A 股使用 DeepSeek
- 美股使用 Gemini

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
  --style momentum
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
拥有、权限精确为 `0600`、不超过 128 KiB。推荐 JSON 格式如下；旧的 UTF-8
`KEY=value` 行格式继续兼容。

```json
{
  "ai_stock_picker": {
    "deepseek": {"api_key": "YOUR_DEEPSEEK_API_KEY"},
    "gemini": {"api_key": "YOUR_GEMINI_API_KEY"}
  }
}
```

解析器不调用 shell 或展开变量，只读取当前 provider 的专属 key；JSON 重复字段、错误
类型和空 key 都会失败。未传 `--credential-file` 时才读取进程环境变量。

结果文件不会覆盖已有文件。重复运行时，请复用已有结果或指定新的输出路径。

`reasoning` 和 `risk_note` 是仅基于候选字段的 AI interpretation，未经独立事实核验，
不应包装成已核验事实或投资建议。每个句子可以使用获批的中英文自然标签引用候选字段，
无需向客户暴露 snake_case 字段名。

## 详细文档

- [文档导航](docs/README.md)
- [输入格式](docs/input-formats.md)
- [输出格式](docs/output-artifact.md)
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
