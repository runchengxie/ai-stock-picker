# 研究展示页：预览和更新

[English](../showcase.md) · 简体中文参考译文；如有差异，以英文为准。

[网站](https://runchengxie.github.io/ai-stock-picker/)首页展示研究发现。工具介绍和安装教程在 `tool.html`。两个页面都不调用模型，不需要 API 密钥。

## 页面收录什么

五项归档研究包括输入顺序稳定性、Flash/Pro 对比、六个月规则回放、新版数值规则和降低换手的组合测试。每日观察单独展示。2026 年 10 月 1 日核对的汇总还没有核验后的连续每日序列，7 月 18 日离线演练明确分开。

持有期切换只对比对应历史结果。模型测试把名单合格与完整结果可用分开；没运行不写成零，失败保留，不编造每日收益曲线。大白话解释见[实验笔记](research/README.md)。

## 数字保存在哪里

生成的数据和预览站点保存在仓库外。`site/research-source.json` 记录已核对 `research.json` 的 release 标签和 SHA-256。Actions 下载精确版本，检查哈希和证据分类，再在 runner 临时目录生成网站。

公开汇总不是私有原始响应的副本，只包含核对指标、来源文件名和内容哈希。原始报告和回执保留在私有研究归档。哈希识别内容，不是独立历史时间证明；release 文件被悄悄改动时，构建会失败。

## 本地预览

下载到数据目录，再生成到仓库外的新路径：

```bash
mkdir -p "$HOME/data/ai-stock-picker/research-site/download"
gh release download research-data-2026-10-01 \
  --repo runchengxie/ai-stock-picker \
  --pattern research.json \
  --dir "$HOME/data/ai-stock-picker/research-site/download"
python scripts/site/build.py \
  --snapshot "$HOME/data/ai-stock-picker/research-site/download/research.json" \
  --output "$HOME/data/ai-stock-picker/research-site/preview"
python -m http.server 8000 \
  --directory "$HOME/data/ai-stock-picker/research-site/preview" \
  --bind 127.0.0.1
```

打开 `http://localhost:8000`。再次构建时选择未使用的输出目录，不覆盖旧内容。版本更新后，用配置里的标签替换示例标签。

## 更新每日观察

每日行必须来自经过 `validate_shadow_day` 校验的真实 owner 日级归档，不能只靠调用方自称 `valid=true`。导入器拒绝离线或启动未绑定演练，只导出允许公开的摘要字段：

```bash
uv run python scripts/site/export_daily.py \
  --snapshot /absolute/path/research.json \
  --day-dir /absolute/path/campaign/arm/provider--model/YYYY-MM-DD \
  --output "$HOME/data/ai-stock-picker/research-site/next-research.json"
```

可以重复 `--day-dir`。校验包含重复运行、共识和冻结启动来源；失败终态保留，不计算收益，也不升级时点或样本外资格。

核对合并后的汇总、数量和指标含义，记录新的核对日期，再以**新的**研究数据 release 发布。通过 PR 更新 `site/research-source.json` 的标签和哈希，不替换旧资产。历史字段只对应那次实验；新实验需要更新合同、图表和笔记，不能覆盖旧结论。

GitHub runner 不能读取私有机器文件系统。准备并核对新数据与部署是两个步骤，网站不声称自动收集每日结果。

## 语言和交互

英文为主，文案保存在 `site/locales/en.json`、`zh-CN.json` 的稳定语义键下。浏览器允许时记住选择，文档链接随语言变化。日期和数字按所选语言显示，日期显式使用 UTC；缺失译文回退英文。

`site/app.js` 渲染研究视图，`research-model.mjs` 放测试过的指标和视图小函数，`tool.js` 维护安装子页。资源用相对路径，适配项目 Pages。生成的 HTML 在 JavaScript 或数据加载失败时仍提供可读英文摘要。

英文 HTML 兜底与语言目录保持一致。英文和中文研究笔记同步更新；不翻译 CLI 选项、字段名和存储标识。

## 检查与发布

运行现有 Python 质量入口，其中包含发布测试：

```bash
uv run python scripts/dev/check.py
node --test tests/site/*.test.mjs
```

检查桌面和手机、语言切换、来源展开、研究筛选、持有期切换、缺数据状态和工具子页，并与汇总逐项核对数字。

Pages Actions 在 PR 上运行前端检查和真实固定数据构建；仅从 `main` 发布生成后的公开站点。权限限制在部署 job，Python 质量检查仍由现有 CI 统一执行。实现参考 [GitHub 官方文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。
