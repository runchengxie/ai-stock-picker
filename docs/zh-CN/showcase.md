# 展示页与自动发布

[English](../showcase.md) · 简体中文参考译文；如有差异，以英文版为准。

[项目展示页](https://runchengxie.github.io/ai-stock-picker/)介绍工具并链接到文档。页面是静态介绍，不是实时选股看板；不调用模型，也不需要 API 密钥。

## 文件位置

- `site/index.html`：页面结构和完整英文兜底文案。
- `site/styles.css`：响应式布局、键盘焦点和减少动画支持。
- `site/app.js`：加载语言目录、切换语言、切换文档链接。
- `site/locales/en.json` 和 `zh-CN.json`：以稳定语义键保存界面文案。
- `.github/workflows/pages.yml`：静态资源检查和发布。

## 本地预览

从仓库根目录执行：

```bash
python -m http.server 8000 --directory site --bind 127.0.0.1
```

打开 `http://localhost:8000`。语言目录通过 `fetch` 加载，因此需要 HTTP 服务；直接双击 HTML 文件不支持语言切换。

## 语言约定

默认英文，英文为权威版本。用户可以切换简体中文；浏览器允许存储时记住明确选择。缺失译文回退英文；语言目录加载失败时保留完整英文页面。文档链接随语言切换。

界面文案放在语言目录中，不在组件里写中文，不按语言更改 JSON 字段名。更新英文时，同时更新 `index.html` 的英文兜底和中文目录。页面没有需要按语言格式化的动态金融数值或时间戳。

主文档位于 `README.md` 和 `docs/*.md`。中文参考在 `docs/zh-CN/`，其中 `README-project.md` 是项目 README，`README.md` 是文档导航，`examples.md` 是示例指南。每页链接到对应英文页。CLI 选项和协议值保持不变；英文文档中的 A 股解释仍按市场要求保留中文。

## Actions 发布

仓库 Settings → Pages 的来源选择 **GitHub Actions**。静态页面不需要自定义域名或仓库密钥。

相关 PR 会检查 JavaScript 语法和 JSON 目录。`main` 的 `site/**` 或发布工作流变化后，上传的内容仅包含 `site/`，再部署到 `github-pages` 环境。也可以从 `main` 手动触发。PR 和其他分支不部署。部署仅授予 `pages: write` 和 `id-token: write`，普通检查只有 `contents: read`。

实现参考 [GitHub 官方文档](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)。Python 质量检查仍由现有 CI 调用 `scripts/dev/check.py`。

## 检查修改

```bash
node --check site/app.js
python -m json.tool site/locales/en.json > /dev/null
python -m json.tool site/locales/zh-CN.json > /dev/null
```

还应检查桌面和手机布局、语言切换、刷新后的选择保存、文档链接，以及存储被阻止或目录请求失败时页面是否可读。合并后确认 Pages 工作流成功，并检查线上页面。
