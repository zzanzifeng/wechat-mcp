# WeChat MCP - 微信本地消息实时读取

> **让 Claude Code 实时读取你的微信聊天记录，从群聊中提取有价值的知识。**

一个 macOS 本地 MCP Server，通过解密微信 SQLCipher 数据库，让 AI 助手实时读取和搜索你的微信消息。所有数据仅在本地处理，不上传任何服务器。

## Use Case

```
你: "提取 GPT-Runner 交流群今天有价值的内容帮助你进化"

Claude Code → wechat_read_group("GPT-Runner", today)
           → 解密本地 msg_N.db
           → 返回今天的群聊消息
           → AI 分析并提取有价值的洞察
```

## Features

- **实时读取** — 直接解密本地微信数据库，延迟 ~100ms
- **群聊提取** — 按群名+日期+关键词精准提取消息
- **全局搜索** — 跨所有聊天的关键词搜索
- **联系人查询** — 模糊匹配联系人/群名
- **智能分析** — AI 分析群聊价值内容并提取洞察
- **本地优先** — 所有数据仅在本地处理，隐私安全
- **无需关闭 SIP** — 使用 Mach VM API 内存扫描提取密钥

> **安全红线**: 本项目**仅读取本地 SQLite 数据库文件**，绝不调用微信任何网络请求接口，不发送消息，不模拟客户端协议，与微信服务器零交互。

## Requirements

- macOS (Apple Silicon / Intel)
- WeChat for Mac (保持登录状态)
- Python 3.11+
- Xcode Command Line Tools

## Quick Links

- [Design Document](docs/plans/2026-03-06-wechat-mcp-design.md) - 完整架构设计
- [Related: ai-rag](https://github.com/zzanzifeng/ai-rag) - AI RAG 知识库项目 (本项目作为数据源之一)

## License

MIT
