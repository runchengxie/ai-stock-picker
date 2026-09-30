# AI Stock Picker

[English](../../README.md) · 简体中文参考译文；如有差异，以英文版为准。

**把你已经准备好的候选股交给 AI，选出指定数量，并保存可检查的结果。**

例如：你已有 30 只候选股，希望按质量偏好选出 5 只。这个工具读取候选数据、调用模型重新排序，再检查模型是否只选了池内股票、数量是否正确，最后保存 JSON 结果和运行记录。

[项目展示页](https://runchengxie.github.io/ai-stock-picker/) · [使用指南](usage.md) · [全部文档](README.md)

## 它能做什么

| 你提供 | 工具处理 | 你得到 |
| --- | --- | --- |
| 候选股文件、选择日期和数量 | AI 排序 → 检查结果 → 保存文件 | 选中的股票、基于输入字段的解释、运行记录 |

- **A 股**使用 DeepSeek；**美股**使用 Gemini。
- 模型只能从你提供的候选股中选择，名称和主题取自输入。
- 不负责获取行情、生成候选池、回测或自动下单。

## 第一次运行：不需要 API 密钥

需要 **Python 3.10–3.12** 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。在终端中执行：

```bash
git clone https://github.com/runchengxie/ai-stock-picker.git
cd ai-stock-picker
uv sync --locked --no-dev
```

用仓库自带的 A 股示例检查安装：

```bash
uv run aipick cn pick \
  --candidates examples/cn_candidates.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

成功时，终端会显示候选数量、模型和 Prompt 等计划摘要。`--dry-run` 不读取密钥、不调用模型，也不生成结果文件。

示例只有 1 只股票，用于验证流程。日期与示例数据对应，不要改成今天；它不是当前股票推荐。美股示例见[示例说明](examples.md)。

## 生成一次真实的模型结果

移除 `--dry-run`，提供对应市场的密钥和输出路径即可。下面继续使用同一份历史示例，正式调用模型会产生 API 费用：

```bash
export DEEPSEEK_API_KEY='你的 DeepSeek 密钥'
mkdir -p "$HOME/data/ai-stock-picker"
uv run aipick cn pick \
  --candidates examples/cn_candidates.json \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --output "$HOME/data/ai-stock-picker/cn-selection.json"
```

成功后得到：

- `cn-selection.json`：通过校验的选择结果。
- `cn-selection.json.evidence/`：输入、Prompt、脱敏请求、原始响应和校验记录。

已有文件或证据目录不会被覆盖。再次运行时，请换一个输出路径。用于自己的研究时，把示例替换为你准备的候选池。

美股命令、模型参数、安全凭据文件和常见错误见[使用指南](usage.md)。

## 接下来读什么

| 你想做的事 | 文档 |
| --- | --- |
| 使用自己的数据 | [输入格式](input-formats.md) |
| 理解结果文件 | [输出格式](output-artifact.md) |
| 检查一次运行记录 | [证据归档](evidence-and-stability.md) |
| 做重复运行和对照实验 | [进阶研究](shadow-research.md) |
| 修改项目或运行完整检查 | [开发与检查](development.md) |

AI 解释仅基于候选数据，未经独立事实核验。可追溯的运行记录不代表收益保证或严格的历史时点证明；输出用于研究，不构成投资建议。
