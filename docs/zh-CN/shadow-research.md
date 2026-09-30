# 进阶研究：重复运行与对照实验

[English](../shadow-research.md) · 简体中文参考译文；如有差异，以英文版为准。

如果你只想从候选池中选出几只股票，不需要阅读本页。先看[使用指南](usage.md)。

这里的实验用于检查模型排序是否稳定，以及它是否受到股票身份或输入顺序的影响。它们不能证明未来收益。实验结果与正式选择结果分开保存。

## 先理解这些词


- 影子实验（shadow）：与正式发布隔离的对照实验；先固定候选池、Prompt、模型与推理参数，再重复调用模型。归档后的结果可以离线复验，用来检验结论是否稳定。
- 受边界约束的排序臂（bounded arm）：对边界股票做约束排序的实验臂，需最终三只边界股票各至少两票才进入完成态（complete）。
- 风险否决臂（risk-veto arm）：命中 `veto_symbol/risk_code` 时拦截结果的实验臂，要求完全相同的符号和风险代码组合至少两票。
- 前瞻影子（prospective shadow）：面向未来交易时段、先冻结再发布的影子实验，区别于历史回放。
- 决策计划（decision plan）：冻结实验活动（campaign）/date/arm、Prompt、候选与数值（Numeric）证据的不可变工件 `ai_shadow_decision_plan`。
- 发布回执（launch receipt）：在决策计划基础上再冻结模型服务提供方（provider）、model 与完整推理参数的授权工件 `ai_shadow_launch_receipt`。
- 墓碑（tombstone）：标记某次运行或重复单元失败的终态，与成功终态完成态（complete）相对。
- 共识（consensus）：多次重复经真多数投票达成的一致结论，先完整落盘到隔离暂存（staging）再原子发布。
- Borda 共识（Borda）：用 Borda 计票汇总多个排序的共识方法，旧版 `.7` 目录仍按原合同只读重建。
- 数值排名（Numeric）：按数值打分排序的方法，替补顺序只由它决定。
- 清单（manifest）：描述本次运行产物的元数据清单，例如 `legacy_unbound` 标记。
- 产物（artifact）：一次运行产出的校验后 JSON 与 append-only 证据目录。

## 当前实验流程（`.8`）


`.8` 已实现 `bounded_ranking_v3 / 2026-07-18.8` 与
`risk_veto_v1 / 2026-07-18.8` 的严格解析、三次重复、真多数共识和 tombstone。
bounded arm 只有在最终三只边界股票各获得至少两票时才 complete。risk-veto arm 要求
完全相同的 `veto_symbol/risk_code` 至少两票，替补只能由 Numeric 顺序确定。每次 repetition 以及
consensus 都先在隔离 staging 完整落盘，再原子发布为 complete 或 tombstone 终态。已有
目录不会覆盖。artifact 内嵌相对路径 candidate snapshot，不复制原始绝对路径。

正式 `.8` 路径使用两个不可变工件解除旧 `ai_pick_plan` 的 DeepSeek 身份绑定：
`ai_shadow_decision_plan` 只冻结 campaign/date/arm、Prompt、候选和 Numeric 证据。
`ai_shadow_launch_receipt` 再冻结 provider、model 和完整推理参数。二者使用规范化 JSON 内容
哈希，receipt 绑定 decision digest，runner 只能由 receipt 构造 model partition：

```bash
uv run aipick cn shadow-decision-plan \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id prompt-8-prospective \
  --signal-date 2026-07-18 \
  --output-dir /absolute/path/lineage/decision

uv run aipick cn shadow-launch-receipt \
  --decision-plan /absolute/path/lineage/decision/decision-plan.json \
  --provider openai \
  --model gpt-model-snapshot \
  --output-dir /absolute/path/lineage/openai-receipt

uv run aipick cn shadow-day \
  --plan /absolute/path/frozen/plan.json \
  --decision-plan /absolute/path/lineage/decision/decision-plan.json \
  --launch-receipt /absolute/path/lineage/openai-receipt/launch-receipt.json \
  --campaign-id prompt-8-prospective \
  --signal-date 2026-07-18 \
  --output-root /absolute/path/shadow
```

缺少任一工件时，标准 `.8 shadow-day` 在调用 provider 前 fail closed。显式注入 caller 的
旧 cosplay 仍可重放，但 manifest/validator 只能标记为 `legacy_unbound`，不会冒充
`prospective_bound`。

历史 `.7` 进程中断导致 repetition 缺失时，可使用无网络 watchdog 将缺失单元写为 tombstone：

```bash
uv run aipick cn shadow-watchdog \
  --plan /absolute/path/frozen/plan.json \
  --campaign-id legacy-bounded-v2 \
  --signal-date 2026-07-17 \
  --output-root /absolute/path/shadow \
  --provider deepseek \
  --model deepseek-v4-flash
```

下游不需要复制 owner schema。使用 `contract-info` 获取带摘要的机器合同，并通过 owner
CLI 离线校验 artifact。日级 validator 同时返回已验证的 `plan_sha256`、
`decision_plan_sha256`、`launch_receipt_sha256`、`evidence_status`、
`numeric_ranking_sha256` 和 candidate 哈希，供下游绑定完整 lineage：

```bash
uv run aipick cn contract-info
uv run aipick cn contract-info --json-schema
uv run aipick cn validate-shadow-day --day-dir /absolute/path/shadow/day
uv run aipick cn validate-shadow-campaign --campaign-root /absolute/path/shadow/campaign
```

新目录为 `campaign/arm/provider--model/date/repetition`。冻结的 `.7` 计划、旧目录和旧
Borda 共识仍按原合同只读重建与校验，不会被 `.8` 覆盖。


关于证据文件和匿名对照，继续阅读[证据归档与稳定性试验](evidence-and-stability.md)。
