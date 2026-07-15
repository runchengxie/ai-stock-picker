# AGENTS.md

## 项目目标

本仓库提供严格、可审计的候选股重排工具。

当前公开命令只有：

```text
aipick cn pick
aipick us pick
```

候选池由外部系统生成。本仓库负责校验输入、构建 prompt、调用对应模型、校验模型输出并发布结果文件。

## 核心约束

修改代码时必须保留以下约束：

1. 模型只能选择候选池中的股票。
2. 股票名称和主题只能从候选池回填。
3. A 股只能使用 `DEEPSEEK_API_KEY`。
4. 美股只能使用 `GEMINI_API_KEY`。
5. provider 凭据不能进入 URL。
6. provider 凭据不能随重定向转发。
7. 模型输出必须通过 strict schema 校验。
8. 输出数量必须与 `top_n` 完全一致。
9. 输出股票代码必须唯一。
10. 已存在的结果文件不能被覆盖。
11. A 股的 `reasoning` 和 `risk_note` 必须包含中文。
12. 输出不能声称具备严格时点证明或样本外证据资格。

## 主要目录

```text
src/stock_analysis/
├── app/cli.py
└── ai_lab/
    ├── candidates.py
    ├── contracts.py
    ├── providers.py
    └── selection.py

tests/
examples/
scripts/dev/
docs/
```

主要职责：

- `candidates.py` 读取、校验和归一化候选池
- `contracts.py` 定义模型输出和结果文件
- `providers.py` 调用 DeepSeek 与 Gemini
- `selection.py` 构建 prompt、校验结果并写入文件
- `app/cli.py` 处理命令行参数和错误输出

## 开发命令

安装依赖：

```bash
uv sync --locked --group dev
```

运行完整检查：

```bash
uv run python scripts/dev/check.py
```

项目不使用 pre-commit、GitHub Actions 质量工作流或 Makefile。不要为同一套检查重新创建多个独立入口。

## 测试要求

新增或修改行为时，应覆盖：

- 正常输入
- 缺失字段
- 错误类型
- 边界数值
- 重复股票
- 候选池外股票
- 时区和日期边界
- provider 错误
- 凭据隔离
- 文件已存在
- 并发写入

测试不能访问真实 provider。provider 调用应通过 transport、caller 或 monkeypatch 完成。

## Prompt 与 schema

修改以下内容时，需要同步更新测试和文档：

- prompt 结构
- prompt 语言约束
- provider 默认模型
- 模型输出字段
- artifact 字段
- 输入契约
- 时间与证据限制

改变 prompt 语义时更新 `PROMPT_VERSION`。

改变持久化 schema 时更新 schema 版本，并说明兼容性影响。

## 文档同步

以下变更必须同步更新 README 或 `docs/`：

- CLI 参数
- 环境变量
- 输入格式
- 默认模型
- style 选项
- 输出字段
- 开发命令
- Python 支持版本

README 只保留新人上手所需内容。字段级契约、架构设计和开发细节放在 `docs/`。

## 安全要求

- 不提交 API 密钥。
- 不在错误信息中输出凭据或底层网络细节。
- 不允许候选字符串改变 prompt 指令。
- 不降低输入、响应和字符串长度限制，除非变更附有明确理由和测试。
- 不允许普通 JSON 或 CSV 通过自报字段升级为受信任契约。

## 修改原则

优先使用清晰、直接的实现。

当前只支持两个固定 provider，无需提前引入插件框架或复杂依赖注入容器。

模块拆分应基于职责，避免为了减少行数创建大量缺少独立意义的小文件。
