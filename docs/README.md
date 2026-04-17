# 项目文档索引

本目录存放 WeChat Decrypt 的研发、架构、测试、部署与运维文档。按顺序阅读可快速建立全貌。

| 文档 | 内容 | 适合谁读 |
|---|---|---|
| [01-objectives.md](01-objectives.md) | 研发目标、范围、非目标、用户画像、交付物概览、合规声明 | 产品/负责人 |
| [02-architecture.md](02-architecture.md) | 分层架构、关键文件职责、控制流、SQLCipher 4 参数、实时监听内部、图片格式、MCP、数据流 | 开发者 |
| [03-test-cases.md](03-test-cases.md) | 20 个自动化单元测试清单 + 9 类手工验收用例 + 新增用例模板 | QA / 开发者 |
| [04-deployment.md](04-deployment.md) | 环境要求、两种部署形态、分平台部署步骤、配置字段、MCP 集成、升级、卸载 | 部署工程师 |
| [05-operations.md](05-operations.md) | 启停、日志阅读、10 类故障排查、监控指标、定期维护、紧急回滚 | 运维 / 最终用户 |
| [06-delivery.md](06-delivery.md) | **跨机交付手册**: 服务端 + 客户端完整部署步骤、mcp-proxy 桥、安全清单、30 秒验证序列 | 把服务搬到另一台机器的人 |
| [README-network.md](README-network.md) | **网络 MCP 详细参考**: `network` 段全字段、IP+Domain 双路径白名单、stdio-only 客户端桥接、TLS、故障表 | 开发者 / 运维 |

> 现有的平台专题文档仍保留在本目录，作为补充参考:
>
> - [macos-3x-vs-4x-decryption-guide.md](macos-3x-vs-4x-decryption-guide.md)
> - [macos-permission-guide.md](macos-permission-guide.md)

## 项目根目录的其它关键文档

- [`README.md`](../README.md) — 仓库说明、快速开始、Web UI、MCP 使用范例、技术细节
- [`USAGE.md`](../USAGE.md) — MCP 集成到 Claude Code 后的对话示例
- [`CLAUDE.md`](../CLAUDE.md) — 为 Claude Code 定制的上下文提示
