# 证据归档与稳定性试验

## 调用证据

`pick` 和 `trial` 每次调用模型后都会写入独立的证据目录。未传
`--evidence-dir` 时，目录默认为 `<output>.evidence`。目录和结果文件都采用追加写入，
已有内容不会被覆盖。

证据目录包含：

- `candidate_input.json` 或 `candidate_input.csv`，候选池原文件
- `numeric_ranking.json`，完整数值排名
- `prompt.txt`，实际发送的 Prompt
- `http_request_envelope.json`，凭据已脱敏的请求信息
- `provider_request_body.json`，不含凭据的请求正文
- `provider_response_body.bin`，模型服务返回的原始响应字节
- `model_response.txt`，成功提取的模型正文
- `selection.json`，通过校验的选择结果
- `ranking_diagnostic.json`，排序通过但发布失败时保存的股票顺序
- `manifest.json`，状态、时间、模型信息和逐文件哈希

新写入的 evidence v2 会在 `provider_parameters` 中保存完整推理参数。DeepSeek 关闭推理
时保存 `thinking=disabled`、`max_tokens`、`temperature` 和 JSON 输出格式。开启推理时
保存 `thinking=enabled`、`reasoning_effort`、`max_tokens` 和 JSON 输出格式，请求中不含
`temperature`。校验器会将这些参数与 `provider_request_body.json` 逐项核对。

匿名 production 计划生成的证据还会保存 `symbol_aliases`、`name_aliases` 和
`alias_maps_sha256`。组合哈希的输入是包含上述两个字段的规范化 JSON，字段排序、两空格
缩进、UTF-8 编码并以一个换行结尾。校验器会用归档候选池重新生成完整 Prompt，并复算
映射哈希。

`manifest.json` 同时记录请求使用的模型别名和响应返回的实际模型标识。DeepSeek 对应响应
顶层的 `model`，Gemini 对应 `modelVersion`。服务未返回该字段时记录为空，后续分析应将
模型身份视为未确认。

HTTP 调用成功后，响应仍可能出现无效 JSON、错误的顶层类型或缺少模型正文。此类调用会
保存原始响应，状态记为 `rejected`，并且不会生成 `model_response.txt` 和结果文件。错误
信息不会包含凭据或底层响应正文。

证据清单分别记录三个合同：

- `transport_contract` 检查服务响应能否提取为模型正文
- `ranking_contract` 检查结构、数量、唯一性和候选池成员关系
- `publication_contract` 检查文案 grounding、安全边界和完整发布契约

排序合同通过而发布合同失败时，状态仍为 `rejected`。此时会生成
`ranking_diagnostic.json`，业务数据仅含按模型输出顺序排列的股票代码。研究程序可以据此
分析纯排序表现，交付程序仍需看到正式的 `selection.json` 才能发布结果。

校验命令如下：

```bash
uv run aipick cn validate-evidence \
  --evidence-dir /absolute/path/selection.evidence
```

目录缺少清单、文件哈希不符或出现未登记文件时，校验会失败。

## 冻结 production 选择计划

`pick-plan` 可以为批量回放冻结单次 production v4 请求。它不读取凭据，也不调用模型。
展示顺序文件必须是 JSON 字符串数组，并且包含候选池中的全部股票代码，各出现一次。

```bash
uv run aipick cn pick-plan \
  --candidates /absolute/path/candidates/20260715/candidate_universe.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --model deepseek-v4-pro \
  --prompt-profile production_v4 \
  --presentation-order-file /absolute/path/orders/20260715_shuffle.json \
  --symbol-aliases-file /absolute/path/aliases/20260715_symbols.json \
  --name-aliases-file /absolute/path/aliases/20260715_names.json \
  --thinking enabled \
  --reasoning-effort max \
  --max-tokens 32768 \
  --campaign-id deepseek_v4_pro_month_v1_20260716 \
  --trial-id 20260715_pro_shuffle \
  --output-dir /absolute/path/plans/20260715_pro_shuffle
```

冻结目录包含：

- `candidate_input.json` 或 `candidate_input.csv`
- `numeric_ranking.json`
- `prompt.txt`
- `plan.json`
- `receipt.json`
- `symbol_aliases.json` 和 `name_aliases.json`，仅匿名计划包含

`plan.json` 保存 `campaign_id`、`trial_id`、模型、`provider_parameters`、候选哈希、Prompt
哈希和展示顺序。匿名计划还保存两份映射、各自的文件哈希和组合哈希。两份映射必须同时
提供，覆盖完整候选池，且别名必须唯一。`receipt.json` 绑定 `plan.json` 中除文件索引外的
核心字段，文件索引绑定目录内每个输入文件的精确字节。执行时计算完整 `plan.json` 的
SHA-256，并写入证据清单。执行方式如下：

```bash
uv run aipick cn trial \
  --plan /absolute/path/plans/20260715_pro_shuffle/plan.json \
  --output /absolute/path/results/20260715_pro_shuffle.json \
  --evidence-dir /absolute/path/results/20260715_pro_shuffle.evidence
```

`trial` 会重新读取候选快照并重建 Prompt，核对所有文件和哈希后才会访问模型。命令没有
模型、推理模式或输出预算覆盖参数，因此实际请求只能使用冻结值。匿名计划还会检查完整
Prompt，任何真实股票代码或名称残留都会使执行失败。

## 五臂稳定性计划

`stability-plan` 只生成试验材料，不读取凭据，也不访问网络。每个日期固定生成五个实验
臂，顺序如下：

1. `canonical`，标准渲染顺序
2. `shuffle_101`，使用种子 101 打乱最终渲染顺序
3. `shuffle_202`，使用种子 202 打乱最终渲染顺序
4. `shuffle_303`，使用种子 303 打乱最终渲染顺序
5. `opaque_404`，保留标准顺序，并匿名处理股票代码和名称

三个 shuffle 臂必须互不相同，也必须不同于标准顺序。若候选数量过少导致固定种子无法
满足约束，计划生成会失败。

匿名编号按以下过程生成：

1. 对每只股票计算紧凑 JSON 数组
   `[campaign_id, selection_as_of, symbol, 404]` 的 SHA-256。
2. 按哈希值和股票代码排序。
3. 依次分配代码 `C001`、`C002` 和名称 `候选001`、`候选002`。
4. 将真实身份、匿名身份和身份哈希写入 `identity_mapping`。

匿名臂会检查整个 Prompt，真实股票代码和名称均不得出现。主题及其他文本中的身份引用也
会同步替换，全部数值字段保持不变。模型返回结果先在匿名标识空间校验，再依据映射还原。

## Prompt 版本隔离

正式 `pick` 使用 production v4，版本为 `2026-07-17.6`。该版本移除了首行真实股票
示例，每个候选只保留顶层 `score`，并增加 `source_topics` / `source_concepts` 的字段
隔离与显式候选值引用规则。

稳定性五臂使用冻结的 legacy v3，版本为 `2026-07-15.3`。它保留旧算法中的首行示例和
顶层、`features` 内重复的 `score`，便于复现已经预注册的实验。两套构建器分别校验。
production `plan.json` 通过正式写入器生成结果。legacy v3 `trial.json` 走研究专用写入器，
并持续标记为 `eligible_as_oos_evidence=false`。

单日计划示例：

```bash
uv run aipick cn stability-plan \
  --candidates /absolute/path/candidates/20260715/candidate_universe.json \
  --as-of 2026-07-15 \
  --top-n 10 \
  --style momentum \
  --campaign-id deepseek_stability_v1_20260716 \
  --output-dir /absolute/path/stability/20260715
```

相同候选池、`campaign_id` 和参数会生成逐字节一致的 `trial.json` 与 `prompt.txt`。
顶层清单另行记录生成时间、固定种子及全部文件哈希。

## 一次生成预注册的 20 个日期

以下命令不会调用 DeepSeek。示例假设候选文件位于
`$candidate_root/<YYYYMMDD>/candidate_universe.json`。首次执行前应确认有效日期确为 116
个，并冻结完整日期清单和候选文件哈希。

```bash
candidate_root=/absolute/path/candidates
output_root=/absolute/path/stability-plans
campaign_id=deepseek_stability_v1_20260716

for date in \
  20260115 20260123 20260202 20260210 20260226 \
  20260306 20260316 20260324 20260401 20260410 \
  20260421 20260429 20260512 20260520 20260528 \
  20260605 20260615 20260624 20260707 20260715
do
  iso_date="${date:0:4}-${date:4:2}-${date:6:2}"
  uv run aipick cn stability-plan \
    --candidates "$candidate_root/$date/candidate_universe.json" \
    --as-of "$iso_date" \
    --top-n 10 \
    --style momentum \
    --campaign-id "$campaign_id" \
    --output-dir "$output_root/$date"
done
```

有效日期数量变化时，应按预注册公式
`round(i * (n - 1) / 19)` 重新选取 20 个日期，并在计划外单独记录差异。

## 运行单个实验臂

```bash
uv run aipick cn trial \
  --plan /absolute/path/stability/20260715/trials/shuffle_101/trial.json \
  --output /absolute/path/results/20260715_shuffle_101.json \
  --evidence-dir /absolute/path/results/20260715_shuffle_101.evidence
```

`trial` 会按 `trial.json` 中的版本重建 Prompt，并要求字节内容与冻结文件完全一致，然后
才会调用模型。

## 解释边界

证据目录可以说明某次运行使用了哪些本地材料，也能发现后续改写。历史文件是否在当时
已经存在，仍需外部发布回执或持续的追加式时间记录证明。回放结果继续作为研究证据，
不具备正式样本外资格。
