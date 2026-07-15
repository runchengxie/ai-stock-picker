# AI Stock Picker

`ai-stock-picker` 接收版本化候选池，调用用户选择的模型重新排序，并输出经过严格校验的 JSON 结果。

完整流程：

```text
候选 manifest → 模型重排 → 选股 manifest
```

市场由候选 manifest 声明。模型 provider、model、排序风格和输出语言由运行参数决定，彼此独立。

项目不采集行情，不生成候选池，不回测，也不下单。

## 安装

需要 Python 3.10 至 3.12 和 `uv`。

```bash
uv sync --locked --group dev
uv run aipick --help
```

## 先执行 dry-run

下面用 DeepSeek 重排美股候选池：

```bash
uv run aipick pick \
  --candidates "$PWD/examples/us_candidates.json" \
  --as-of 2026-07-15 \
  --top-n 2 \
  --style growth \
  --response-language en \
  --provider deepseek \
  --dry-run
```

下面用 Gemini 重排 A 股候选池：

```bash
uv run aipick pick \
  --candidates "$PWD/examples/cn_candidates.json" \
  --as-of 2026-07-15 \
  --top-n 1 \
  --style quality \
  --response-language zh-CN \
  --provider gemini \
  --dry-run
```

`dry-run` 会校验输入、解析市场、构建 prompt 并计算哈希，不访问模型，也不写结果文件。

## 正式运行

以 DeepSeek 为例：

```bash
export DEEPSEEK_API_KEY='你的密钥'

uv run aipick pick \
  --candidates /absolute/path/candidates.json \
  --output /absolute/path/selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style quality \
  --response-language zh-CN \
  --provider deepseek \
  --model deepseek-chat
```

以 Gemini 为例：

```bash
export GEMINI_API_KEY='你的密钥'

uv run aipick pick \
  --candidates /absolute/path/candidates.json \
  --output /absolute/path/selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --response-language en \
  --provider gemini \
  --model gemini-2.5-flash
```

也可以连接 OpenAI-compatible HTTPS 接口：

```bash
export CUSTOM_MODEL_API_KEY='你的密钥'

uv run aipick pick \
  --candidates /absolute/path/candidates.json \
  --output /absolute/path/selection.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style growth \
  --response-language en \
  --provider openai-compatible \
  --model your-model \
  --base-url https://provider.example/v1/chat/completions \
  --api-key-env CUSTOM_MODEL_API_KEY
```

结果文件不会覆盖已有文件。

## 迁移旧 CSV

核心选股命令只接受版本化 JSON。旧 CSV 可以先显式转换：

```bash
uv run aipick migrate-csv \
  --input legacy.csv \
  --output candidates.json \
  --market US \
  --observation-date 2026-07-14 \
  --generated-at 2026-07-15T00:00:00+00:00 \
  --data-cutoff 2026-07-14
```

## 文档

- [输入格式](docs/input-formats.md)
- [模型 provider](docs/providers.md)
- [输出格式](docs/output-artifact.md)
- [时间与证据边界](docs/trust-boundaries.md)
- [项目架构](docs/architecture.md)
- [开发与检查](docs/development.md)

## 本地检查

```bash
uv run python scripts/dev/check.py
```

该命令运行依赖锁、Ruff、格式、`ty`、测试、覆盖率基线、维护性检查和构建。

模型输出仅用于研究和流程衔接，不构成投资建议。
