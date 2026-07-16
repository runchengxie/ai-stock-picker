# 项目架构

## 发布边界

本项目只负责候选池生成之后的模型重排。

输入：

- 外部生成的 A 股或美股候选池
- 选择信号日期
- 需要返回的数量
- 选择风格

输出：

- 经过严格校验的 `ai_stock_selection` JSON 文件

项目不包含行情采集、候选生成、回测、通知和订单执行。

## 调用流程

```text
CLI 参数
  ↓
读取并校验候选池
  ↓
归一化候选字段
  ↓
构建确定性 prompt
  ↓
调用市场绑定的 provider
  ↓
校验模型 JSON
  ↓
从候选池回填名称和主题
  ↓
构建 SelectionArtifact
  ↓
写入 append-only 证据目录
  ↓
原子写入结果文件且拒绝覆盖
```

## 模块职责

### `stock_analysis.app.cli`

负责：

- 命令行参数
- 用户可读错误
- dry-run 摘要
- 调用核心流程

CLI 应保持轻量，不在此处实现候选契约或 provider 解析。

### `stock_analysis.ai_lab.candidates`

负责：

- JSON 和 CSV 读取
- 输入大小限制
- manifest 基础校验
- A 股 v1 契约校验
- 候选字段归一化
- prompt 特征白名单

该模块当前职责较多。后续可以将 A 股契约校验提取到独立模块，同时保留一个统一的候选加载入口。

### `stock_analysis.ai_lab.contracts`

负责：

- 市场、provider 和 style 类型
- 模型输出 schema
- 持久化结果 schema
- 时间、lineage 和 picks 的交叉校验

Pydantic 模型使用 strict、extra forbid 和 frozen 配置，避免隐式类型转换和结果写入后的意外修改。

### `stock_analysis.ai_lab.credentials`

负责安全读取显式传入的 owner 凭据文件，并且只返回 selection plan 对应 provider 的
专属 key。

### `stock_analysis.ai_lab.providers`

负责：

- DeepSeek HTTPS 请求
- Gemini HTTPS 请求
- provider 响应解析
- 响应实际模型标识提取
- HTTP 成功但正文无效时保留原始响应
- 请求和响应大小限制
- 凭据隔离
- 错误信息清洗

A 股只使用 `DEEPSEEK_API_KEY`。

美股只使用 `GEMINI_API_KEY`。

凭据放入不可转发 header，provider 重定向不会携带密钥。

显式传入 `--credential-file` 时，`stock_analysis.ai_lab.credentials` 使用安全文件描述符
读取普通文件：要求当前用户所有、权限精确为 `0600`、大小不超过 128 KiB，并拒绝
符号链接。推荐使用严格 JSON 命名空间
`ai_stock_picker.<deepseek|gemini>.api_key`，旧的 UTF-8 literal `KEY=value` 继续兼容。
两种格式都不执行 shell、不展开 `$()`，并按 selection plan 的 provider 只返回对应
key。JSON 重复字段、错误类型与空 key 会失败。未显式传文件时，provider 才回退读取
自己的进程环境变量。读取前后还会比较文件的 device/inode/size/mtime/ctime 快照。
读取期间即使同 inode 原地改写也会失败。

### `stock_analysis.ai_lab.selection`

负责：

- 选择计划
- provider 调度
- 模型输出校验
- 结果文件构建
- 正式结果与研究结果的隔离写入

### `stock_analysis.ai_lab.prompting`

负责：

- production v4 的 Prompt 渲染
- 冻结 legacy v3 的 Prompt 渲染
- 候选展示顺序
- 股票代码和名称别名
- 匿名文本中的身份替换

production v4 只渲染一份 `score`，也不包含首行真实候选示例。legacy v3 保留旧算法的
重复 `score` 和首行示例，只供预注册稳定性实验使用。

### `stock_analysis.ai_lab.evidence`

负责：

- 保存候选池原文件和完整数值排名
- 保存精确 prompt、脱敏 HTTP 请求信息和原始响应
- 记录请求模型别名、响应实际模型、时间、逐文件哈希和最终选择
- 生成标准顺序、三个固定种子 shuffle 和匿名对照共五个实验臂
- 校验证据目录完整性并拒绝覆盖

### `stock_analysis.ai_lab.stability_support`

负责匿名实验臂的哈希编号、可逆身份映射、真实身份清除和数值字段一致性检查。

## 依赖方向

推荐依赖方向：

```text
cli
├── selection
│   └── prompting + candidates + contracts + credentials + providers
└── evidence
    └── selection + stability_support
```

约束：

- `contracts` 不依赖 CLI
- `providers` 不依赖候选文件格式
- `candidates` 不访问 provider
- 测试通过注入 caller 或 transport 隔离网络

## 名称说明

当前名称分为三层：

- 发布包名：`ai-stock-picker`
- CLI：`aipick`
- Python namespace：`stock_analysis`

`stock_analysis` 来自项目早期阶段，覆盖范围大于当前产品边界。

将 namespace 调整为 `ai_stock_picker` 更符合当前产品定位，但这会改变所有 import、打包配置和外部调用路径。该迁移适合单独提交，便于评审兼容性和回滚。本轮文档与工具链整理保留现有 namespace，不在同一个 PR 中混入破坏性重命名。

## 示例文件

`examples/` 保存可运行的输入示例，也用于验证文档命令。

示例文件不属于运行输出，因此不移动到 `artifacts/`。`artifacts/` 容易被理解为程序生成结果或构建产物。

## 已知后续工作

建议按独立 PR 处理：

1. 将 Python namespace 迁移为 `ai_stock_picker`
2. 拆分 `candidates.py` 的通用加载与 A 股契约校验
3. 为美股定义正式版本化输入契约
4. 将 legacy CSV 移至显式迁移命令，并在核心流程中逐步弃用
5. 避免在持久化 lineage 中写入本地绝对路径

这些调整涉及公共接口或持久化格式，不应和文档及工具链变更捆绑成一次难以审查的大改动。
