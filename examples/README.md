# 示例文件

本目录保存可以直接用于 dry-run 的候选池输入。

## A 股

文件：

- `cn_candidates.json`

特点：

- 符合 `hot_sector_candidate_universe` v1 契约
- 包含 1 个候选
- 适合配合 `--top-n 1`

运行：

```bash
uv run aipick cn pick \
  --candidates "$PWD/examples/cn_candidates.json" \
  --as-of 2026-06-30 \
  --top-n 1 \
  --style momentum \
  --dry-run
```

## 美股

文件：

- `us_candidates.json`

特点：

- 使用通用 JSON manifest
- 包含 2 个候选
- 适合配合 `--top-n 1` 或 `--top-n 2`

运行：

```bash
uv run aipick us pick \
  --candidates "$PWD/examples/us_candidates.json" \
  --as-of 2026-07-15 \
  --top-n 2 \
  --style quality \
  --dry-run
```

## 为什么保留 `examples/`

这些文件是输入示例，帮助使用者理解格式并验证安装结果。

它们不属于程序生成输出，因此不放入 `artifacts/`。生成的选择结果应写入调用者指定的位置，仓库不会提供默认输出目录。

完整字段说明见 [`../docs/input-formats.md`](../docs/input-formats.md)。
