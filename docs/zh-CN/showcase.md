# 研究展示页：预览和维护

[English](../showcase.md) · 简体中文参考译文；如有差异，以英文为准。

[研究站](https://runchengxie.github.io/ai-stock-picker/)是了解项目结果的主要入口。首页展示核对过的对比，每项研究都有中英文大白话笔记。[工具页](https://runchengxie.github.io/ai-stock-picker/tool.html)介绍如何安装和试用命令行工具。两者都是静态网页，不调用 AI 模型，也不需要 API 密钥。

## 页面展示什么

网站收录五项归档研究：模型稳定性、Flash 与 Pro 对比、两次规则回放和一次换手实验。失败的检查和缺失结果也会显示。当前汇总还没有核验后的连续每日序列；7 月 18 日的离线演练单独标出。这些都是历史研究，不是投资建议，也不能证明工具适合实盘。

网页由 Astro 7 构建。默认英文，读者可以切换语言和深色模式；浏览器允许时会记住选择。`docs/research/` 和 `docs/zh-CN/research/` 中的笔记是正文唯一来源，Astro 直接读取，并检查每篇英文笔记是否都有一篇中文译文。

## 本地预览

安装 Node.js 24 和仓库锁定的 npm 依赖。下载 `site/research-source.json` 中指定的数据版本，通过校验后暂存到仓库外，再构建到仓库外的新目录：

```bash
npm ci
gh release download research-data-2026-10-01 \
  --repo runchengxie/ai-stock-picker \
  --pattern research.json \
  --dir "$HOME/data/ai-stock-picker/research-site/download"
uv run python scripts/site/stage_snapshot.py \
  --snapshot "$HOME/data/ai-stock-picker/research-site/download/research.json" \
  --output "$HOME/data/ai-stock-picker/research-site/research.json"
export AIPICK_RESEARCH_SNAPSHOT="$HOME/data/ai-stock-picker/research-site/research.json"
npm run check
npm run build -- --outDir "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker"
mkdir -p "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker/data"
cp "$AIPICK_RESEARCH_SNAPSHOT" \
  "$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker/data/research.json"
AIPICK_SITE_OUTPUT="$HOME/data/ai-stock-picker/research-site/preview-20261002/ai-stock-picker" \
  node --test tests/site/*.test.mjs
python -m http.server 8000 \
  --directory "$HOME/data/ai-stock-picker/research-site/preview-20261002" \
  --bind 127.0.0.1
```

打开 `http://localhost:8000/ai-stock-picker/`。每次构建使用新的预览目录，不要把生成文件放进仓库。数据版本更新后，以 `site/research-source.json` 中的新标签替换示例标签。

## 自动发布怎么做

Pages 工作流会在 PR 上检查内容、前端、数据和生成的页面。它下载固定版本，使用 `scripts/site/stage_snapshot.py` 校验 SHA-256 和公开字段，再把静态网站构建到 runner 临时目录。只有 `main` 上成功的构建会部署。

公开 JSON 只包含核对过的汇总结果和来源指纹，不包含私有候选池、Prompt、原始模型响应或凭据。哈希能识别文件内容，但不能证明文件创建时间。更新 release 标签或哈希需要通过 PR 审核。新数据应发布为新的 release 资产，不要替换旧资产。

要加入每日观察，先准备真实的 owner 日级归档，再运行 `scripts/site/export_daily.py`。导出器会检查重复运行、共识和冻结启动来源，并且只导出公开合同允许的字段。它不会计算收益，也不会提高证据等级。核对汇总后，通过 PR 更新数据版本。

## 检查

提交 PR 前运行 Python 检查和前端、内容测试：

```bash
uv run python scripts/dev/check.py
npm ci
npm run check
node --test tests/site/*.test.mjs
```

生成页面的测试需要先完成 Astro 构建，并让 `AIPICK_SITE_OUTPUT` 指向构建目录（上面的预览步骤已展示）；Pages 工作流会自动设置。调整指标时要对照数据核验页面显示，并同步更新英文笔记和中文参考译文。
