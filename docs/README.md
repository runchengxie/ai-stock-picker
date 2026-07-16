# 项目文档

根目录的 `README.md` 只保留安装和首次运行所需的信息。本目录收录输入契约、输出格式、时间边界、架构和开发流程。

## 使用文档

- [输入格式](input-formats.md)
- [输出格式](output-artifact.md)
- [时间与证据边界](trust-boundaries.md)
- [证据归档与稳定性试验](evidence-and-stability.md)

## 维护文档

- [项目架构](architecture.md)
- [开发与检查](development.md)

## 文档维护约定

修改以下内容时，需要同步更新相应文档：

- CLI 参数
- 环境变量
- 支持的输入格式
- 默认模型和 style
- 输出字段
- 时间与证据语义
- 开发检查命令
- Python 支持版本

根目录 README 面向第一次接触项目的使用者。字段级说明和内部设计放在本目录，避免入口文档再次长成团队会议纪要。
