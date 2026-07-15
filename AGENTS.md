# AGENTS.md

## 项目目标

本仓库实现 provider-neutral 的候选股重排管线：

```text
版本化候选 manifest → 模型重排 → 严格选股 artifact
```

市场由输入 manifest 声明。provider、model、style 和输出语言由运行参数决定。

## 核心约束

1. 模型只能选择候选池中的股票。
2. 股票名称和主题只能从候选 manifest 回填。
3. provider 凭据不能进入 URL。
4. provider 凭据不能随重定向转发。
5. OpenAI-compatible endpoint 必须使用 HTTPS。
6. 模型输出必须通过 strict schema 校验。
7. 输出数量必须与 `top_n` 完全一致。
8. 输出股票代码必须唯一。
9. 已存在的结果文件不能被覆盖。
10. `zh-CN` 输出的解释字段必须包含 CJK 汉字。
11. 输出不得声称具备严格时点证明或样本外证据资格。
12. `generation_trace` 只保存逻辑文件名和内容哈希，不能保存本地绝对路径。

## 主要模块

候选输入：

- `candidate_io.py`
- `candidate_contracts.py`
- `hot_sector_v1.py`
- `candidate_normalization.py`
- `candidate_models.py`
- `candidates.py`
- `csv_migration.py`

模型选择：

- `prompting.py`
- `providers.py`
- `selection.py`
- `storage.py`
- `contracts.py`
- `cli.py`

不要重新把文件读取、契约校验、prompt、网络请求和存储写回同一个模块。

## 开发检查

```bash
uv sync --locked --group dev
uv run python scripts/dev/check.py
```

覆盖率采用 statement 和 branch 基线 ratchet。修改基线时必须说明原因。

## 测试要求

测试不能访问真实 provider。

修改以下行为时必须覆盖正常路径和失败路径：

- 输入契约
- provider 配置和凭据
- 模型输出 schema
- 时间顺序
- generation trace
- 不可覆盖写入
- CSV 迁移

## 文档同步

修改 CLI、输入 contract、provider、输出 schema、环境变量或开发命令时，同步更新 README 和对应 `docs/` 文件。
