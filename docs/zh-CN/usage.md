# 使用指南：从试运行到生成结果

[English](../usage.md) · 简体中文参考译文；如有差异，以英文版为准。

先完成 [README](README-project.md) 中的安装和无密钥试运行，再阅读本页。

一次正式运行需要三样东西：候选股文件、对应市场的 API 密钥，以及一个尚不存在的输出路径。正式运行会访问模型服务，并可能产生 API 费用。

## 命令参数怎么选

| 参数 | 用途 | 示例 |
| --- | --- | --- |
| `--candidates` | 已准备好的候选股文件 | `examples/cn_candidates.json` |
| `--as-of` | 本次选择的信号日期，不是自动获取的今天 | `2026-06-30` |
| `--top-n` | 选择数量，不能超过候选数量 | 示例 A 股文件用 `1` |
| `--style` | 排序偏好 | A 股：`momentum` / `quality`；美股：`quality` / `growth` |
| `--output` | 保存通过校验的结果 | `$HOME/data/ai-stock-picker/selection.json` |
| `--dry-run` | 只检查输入并展示计划摘要 | 无需密钥，不调用模型 |

仓库中的示例是历史输入，只用于学习命令。用于研究时，请自行准备与信号日期对应的候选池；不要仅把日期改成今天。A 股示例含 1 只股票，能验证流程，不能演示多股排序。

## A 股：DeepSeek


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
[证据归档与稳定性试验](evidence-and-stability.md)。

## 美股、凭据与结果归档

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

凭据应保存在仓库外的私有配置目录，不要在 checkout 中留副本。跨仓调用可以改传 `--credential-file /absolute/path/api_keys.json`。文件必须由当前用户
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
当前 production 文案还有精确数值引用要求，详见[输出格式](output-artifact.md)。


## 遇到错误怎么办

| 情况 | 处理方式 |
| --- | --- |
| 提示找不到 `uv` | 按 [uv 安装指南](https://docs.astral.sh/uv/getting-started/installation/) 安装，再打开终端 |
| 提示候选数量不足 | 将 `--top-n` 调小，或提供更大的候选池 |
| 日期校验失败 | 核对 `--as-of` 与候选文件中的观测日期，详见[输入格式](input-formats.md) |
| 缺少 API 密钥 | 设置当前市场对应的环境变量，或传入安全凭据文件 |
| 输出或证据目录已经存在 | 使用一个新的路径，原有结果不会被覆盖 |
| 模型响应被拒绝 | 检查错误说明和证据目录，拒绝结果不会作为正式选择发布 |

研究对照实验见[进阶研究](shadow-research.md)。开发检查见[开发文档](development.md)。
