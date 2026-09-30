# 文档导航

[English](../README.md) · 简体中文参考译文；如有差异，以英文版为准。

第一次使用请从 [README](README-project.md) 开始：先安装，再用示例做一次无需密钥的试运行。这里按你接下来要完成的任务组织文档。

## 日常使用

| 我想…… | 阅读 |
| --- | --- |
| 配置密钥、选择参数、处理错误 | [使用指南](usage.md) |
| 准备自己的候选股文件 | [输入格式](input-formats.md) |
| 了解结果 JSON 中的字段 | [输出格式](output-artifact.md) |
| 运行仓库示例 | [示例说明](examples.md) |

## 研究与系统集成

| 我想…… | 阅读 |
| --- | --- |
| 检查 Prompt、响应和文件是否一致 | [证据归档与稳定性试验](evidence-and-stability.md) |
| 检查重复运行、匿名对照和研究实验 | [进阶研究](shadow-research.md) |
| 理解记录能证明什么 | [时间与证据边界](trust-boundaries.md) |
| 在下游系统验证结果和绑定回执 | [选择结果校验回执](validation-receipt.md) |

## 开发与维护

- [项目架构](architecture.md)：调用流程和模块职责。
- [开发与检查](development.md)：环境、质量检查和测试要求。
- [展示页与自动发布](showcase.md)：本地预览、语言文案和 GitHub Pages 部署。

英文为权威版本，中文为参考译文；变更时同步更新两种语言。修改 CLI 参数、环境变量、输入或输出格式、默认模型、排序风格、时间语义、开发命令或 Python 版本时，同步更新对应文档。README 保留新人上手所需内容，字段级契约和内部设计放在本目录。
