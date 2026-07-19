# 开发与检查

## 环境

需要：

- Python 3.10 至 3.12
- `uv`

安装锁定依赖：

```bash
uv sync --locked --group dev
```

只安装运行依赖：

```bash
uv sync --locked --no-dev
```

## 统一检查入口

运行完整检查：

```bash
uv run python scripts/dev/check.py
```

该脚本依次运行：

1. `uv lock --check`
2. `ruff check .`
3. `ruff format --check .`
4. `ty check`
5. `pytest`
6. 维护性 ratchet
7. wheel 和 sdist 构建

任一步骤失败后，脚本会立即返回对应退出码。

项目不再维护 pre-commit 配置、GitHub Actions 质量工作流和 Makefile。团队当前不使用这些入口，继续保留只会形成多份重复命令。

需要远程门禁时，应从 `scripts/dev/check.py` 调用同一套检查，避免重新复制每条命令。

## Ruff

检查 lint：

```bash
uv run ruff check .
```

检查格式：

```bash
uv run ruff format --check .
```

自动格式化：

```bash
uv run ruff format .
```

可安全自动修复的问题：

```bash
uv run ruff check . --fix
```

当前代码风格：

- Python 3.10 语法下限
- 行宽 88
- 双引号
- 4 空格缩进

## ty

运行类型检查：

```bash
uv run ty check
```

项目将目标 Python 版本固定为 3.10，并检查：

- `src`
- `scripts`
- `tests`

`ty` 当前仍处于 beta，因此开发依赖固定到明确版本。升级 `ty` 时，应单独更新依赖锁并运行完整检查，确认诊断变化来自工具版本还是代码问题。

项目只维护 ty 这一套强制类型检查配置。类型债通过 ty 的局部覆盖规则登记，新增代码继续执行同一套门禁。

### 迁移基线

当前配置只保留以下限定范围的兼容规则：

- 允许 `tomli` 与 `tomllib` 的跨版本回退导入
- `candidates.py` 暂时忽略一处列表元素收窄差异
- `providers.py` 暂时忽略一处容器返回类型收窄差异
- `tests/test_selection.py` 忽略刻意传入错误 Literal 和修改冻结模型的负向测试

这些规则按模块或测试文件限定，没有全局关闭对应诊断。

后续修改相关代码时，应优先移除对应 override。新增 override 需要在 PR 中解释触发场景和收敛计划。

## 测试

运行默认测试和 75% 分支覆盖率门槛：

```bash
uv run pytest
```

运行单个文件：

```bash
uv run pytest tests/test_cli.py
```

运行单个测试：

```bash
uv run pytest tests/test_cli.py::test_dry_run_is_network_free_and_reports_hashes
```

测试不能访问真实 provider。

provider 行为应通过 caller、transport 或 monkeypatch 注入。

## 维护性检查

```bash
uv run python scripts/dev/maintainability_metrics.py --ratchet
```

当前 ratchet 检查：

- 超过 100 字符的行
- 超过 100、250 和 500 行的函数
- `C901` 文件级忽略项
- 超过 800 和 1200 行的文件
- 超过 1000 行的测试文件

预算只应收紧。放宽预算需要在 PR 中说明原因。

## 构建

```bash
uv run python -m build
```

构建后可在临时环境验证 wheel：

```bash
uv venv /tmp/aipick-wheel
uv pip install --python /tmp/aipick-wheel/bin/python dist/*.whl
cd /tmp
/tmp/aipick-wheel/bin/aipick --help
```

CLI 必须能够在仓库目录外运行。运行时代码不能依赖仓库根目录中的隐式配置或数据文件。

## 依赖变更

修改 `pyproject.toml` 后运行：

```bash
uv lock
uv sync --locked --group dev
uv run python scripts/dev/check.py
```

提交时同时包含 `pyproject.toml` 和 `uv.lock`。

## 提交前检查

至少完成：

```bash
uv run python scripts/dev/check.py
```

修改 CLI、输入契约、输出 schema、provider 或原子写入逻辑时，还应运行相关命令的 dry-run，并确认错误路径不会写入文件。
