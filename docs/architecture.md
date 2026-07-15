# 项目架构

## 流程

```text
版本化候选 manifest
  ↓
文件读取与内容哈希
  ↓
输入契约识别和校验
  ↓
候选字段归一化
  ↓
prompt 构建
  ↓
用户选择的 provider 和 model
  ↓
模型 JSON 校验与候选回填
  ↓
SelectionArtifact v2
  ↓
原子、不可覆盖写入
```

市场属于输入数据语义。provider 属于运行配置，两者没有绑定关系。

## Python namespace

Python namespace 为 `ai_stock_picker`。

发行包名继续使用 `ai-stock-picker`，CLI 继续使用 `aipick`。

旧 namespace `stock_analysis` 已删除。版本提升到 `0.3.0`，明确表达这一破坏性 import 变化。

## 候选侧模块

- `candidate_io.py`：文件读取、JSON 解析、大小限制和输入哈希
- `candidate_contracts.py`：契约识别、公共 manifest 元数据校验
- `hot_sector_v1.py`：热题材 v1 专用校验
- `candidate_normalization.py`：统一候选字段、股票代码和特征边界
- `candidate_models.py`：候选内部数据模型
- `candidates.py`：公共加载 facade
- `csv_migration.py`：旧 CSV 的显式迁移

## 选择侧模块

- `prompting.py`：确定性 prompt 构建
- `providers.py`：provider 配置、HTTPS 调用和响应解析
- `selection.py`：计划构建、模型输出校验和 artifact 组装
- `storage.py`：原子、不可覆盖写入
- `contracts.py`：公共输出 schema 和交叉校验
- `cli.py`：参数解析和用户可读错误

## 依赖方向

```text
cli
  ↓
selection + csv_migration
  ↓
prompting + providers + candidates + storage
  ↓
contracts + candidate contract modules
```

provider 模块不依赖市场专用候选格式。候选模块不访问 provider。storage 不理解 prompt 或 provider。
