# 开发与检查

## 环境

需要 Python 3.10 至 3.12 和 `uv`。

```bash
uv sync --locked --group dev
```

## 统一检查入口

```bash
uv run python scripts/dev/check.py
```

该脚本依次运行：

1. 依赖锁检查
2. Ruff lint
3. Ruff format
4. `ty`
5. pytest 和覆盖率报告
6. 覆盖率基线 ratchet
7. 维护性 ratchet
8. wheel 和 sdist 构建

## 覆盖率

项目不再使用单一的 `--cov-fail-under` 百分比作为质量结论。

覆盖率仍然测量 statement 和 branch 两个维度，并与 `scripts/dev/coverage_baseline.json` 比较。基线只能收紧。覆盖率下降需要先说明原因并显式修改基线。

关键行为仍应通过直接测试保护：

- 输入契约
- provider 凭据隔离
- 模型输出 schema
- 候选池成员限制
- 时间顺序
- 原子不可覆盖写入

覆盖率 ratchet 是退化保险丝，不是测试质量评分。

## ty

`ty` 固定到明确版本。升级时单独运行完整检查并审查诊断变化。

## 测试

测试不能访问真实 provider。网络行为通过 transport、caller 或 monkeypatch 注入。

修改公共 manifest、输出 schema、provider 或存储逻辑时，应补充正常路径、边界和失败路径测试。
