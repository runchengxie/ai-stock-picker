# LLM 选股顺序敏感性实验

这个目录提供一个尽量小、可以单独复现的实验，用来回答一个具体问题：

> 候选信息完全相同，只改变候选展示顺序或隐藏候选身份时，LLM 给出的 Top-N 排名有多稳定？

它复用 `ai-stock-picker` 已有的 frozen plan、固定 shuffle、匿名映射、`trial` 和 append-only evidence，不依赖 `research-workspace`、行情数据库、TuShare 或真实股票池。

## 实验设计

候选池包含 8 个中性合成候选：

- 使用格式合法但用于演示的代码 `999001.SZ` 至 `999008.SZ`
- 名称为 `候选甲` 至 `候选辛`
- 所有候选共享同一个合成主题和概念
- `score` 与 `relevance` 故意设置得比较接近，并存在轻微权衡
- 不包含真实公司基本面、新闻、主题叙事或未来收益

`stability-plan` 固定生成五个 arm：

1. `canonical`：标准顺序
2. `shuffle_101`：固定种子 101
3. `shuffle_202`：固定种子 202
4. `shuffle_303`：固定种子 303
5. `opaque_404`：保持 canonical 顺序，但匿名股票代码与名称

规划阶段不访问模型。每个 live arm 调用一次 provider，因此完整演示通常产生 5 次模型调用。

## 1. 安装

在仓库根目录：

```bash
uv sync --locked --group dev
```

## 2. 生成冻结实验材料

```bash
bash experiments/order-sensitivity/prepare.sh
```

默认输出到：

```text
outputs/order-sensitivity-demo/campaign/
```

该步骤应打印 `api_calls=0`。目录中包含候选快照、numeric ranking、五个 frozen `trial.json` 和对应 Prompt。

如果要使用其他输出目录：

```bash
bash experiments/order-sensitivity/prepare.sh /absolute/path/to/campaign
```

## 3. 运行五个 arm

设置 DeepSeek 凭据：

```bash
export DEEPSEEK_API_KEY='your-key'
```

然后运行：

```bash
bash experiments/order-sensitivity/run.sh
```

默认结果目录：

```text
outputs/order-sensitivity-demo/results/
```

每个 arm 独立保存：

```text
canonical.json
canonical.evidence/
shuffle_101.json
shuffle_101.evidence/
...
```

脚本是可恢复的。已经存在 selection 或 evidence 的 arm 会跳过，不会覆盖已有 provider 证据。

也可以显式传入 campaign 和 result 目录：

```bash
bash experiments/order-sensitivity/run.sh \
  /absolute/path/to/campaign \
  /absolute/path/to/results
```

## 4. 查看稳定性摘要

`run.sh` 最后会自动调用：

```bash
uv run aipick cn stability-summary \
  --campaign-dir outputs/order-sensitivity-demo/campaign \
  --results-dir outputs/order-sensitivity-demo/results \
  --output outputs/order-sensitivity-demo/results/summary.json
```

终端会显示简短摘要，例如：

```text
campaign=order-sensitivity-demo-v1
status=complete
completed_noncanonical_arms=4/4
top1_agreement_vs_canonical=75.0%
exact_ranking_agreement_vs_canonical=25.0%
mean_top_n_jaccard_vs_canonical=0.875
mean_absolute_rank_shift_vs_canonical=0.750
summary_json=.../summary.json
```

这些数字只是格式示意，实际结果由模型调用决定。

`summary.json` 还会逐 arm 保存：

- canonical ranking
- arm ranking 与来源文件
- Top-1 是否与 canonical 一致
- 完整排序是否一致
- Top-N Jaccard overlap
- 共同候选的平均绝对名次变化
- `complete` / `ranking_only` / `rejected` / `missing` 状态

如果模型输出的排序合同通过，但文案发布合同失败，已有 evidence 会生成 `ranking_diagnostic.json`。`stability-summary` 会把它作为 `ranking_only` 结果纳入排序稳定性分析，而不会把该 arm 静默删掉。

## 如何理解结果

这个演示主要用于观察三类现象：

- **顺序敏感性**：三个 shuffle arm 与 canonical 的结果是否明显变化
- **身份敏感性**：`opaque_404` 与 canonical 是否明显变化
- **模型随机性与边界决策**：接近的数值候选是否容易在 Top-N 边界交换顺序

一个 arm 的差异不能证明某种稳定的模型偏差。更严谨的研究应增加：

- 多次独立 repetition
- 多个日期或多个冻结候选池
- 不同模型 / provider
- 预注册比较指标和停止规则
- 对模型版本与推理参数进行严格冻结

本目录的目标是提供一个低门槛、可审计的第一层实验，而不是替代完整研究设计。

## 研究边界

- 合成候选没有真实收益，因此这个实验不能说明策略是否存在 alpha。
- `legacy_stability_v3` 是冻结的研究 Prompt，结果持续标记为 research-only，不应包装成 OOS 投资证据。
- Top-1 agreement、Jaccard 等指标衡量模型输出稳定性，不衡量投资质量。
- 真实股票实验还会受到公司名称、ticker、行业叙事、训练语料和数据时间点等额外因素影响。

这个 demo 故意把问题缩小到“模型面对相同候选信息时是否稳定”。先把这个问题测清楚，再讨论收益率，多少能少制造几张漂亮但没什么含义的回测图。
