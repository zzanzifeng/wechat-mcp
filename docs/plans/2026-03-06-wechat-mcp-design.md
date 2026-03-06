# WeChat MCP: Architecture Design Document

> Date: 2026-03-06
> Status: Draft
> Author: AI-assisted design based on ecosystem research

---

## 1. Vision

构建一个 macOS 本地 MCP Server，让 Claude Code 能够：
- **实时读取** 微信本地加密数据库中的聊天记录
- **精准提取** 按群名/联系人 + 日期 + 关键词定向提取消息
- **智能分析** AI 分析群聊/对话的价值内容并提取洞察
- **后台监控** 监控指定群聊，有价值内容主动通知

核心场景：*"提取 GPT-Runner 交流群今天有价值的内容帮助你进化"*

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────┐
│                 Claude Code CLI                   │
│               (MCP Client / 消费方)               │
└────────────────────┬────────────────────────────┘
                     │ MCP Protocol (stdio)
┌────────────────────▼────────────────────────────┐
│              WeChat MCP Server                    │
│                                                  │
│  ┌────────────┐ ┌────────────┐ ┌─────────────┐  │
│  │ Chat Tools │ │Search Tools│ │ Watch Tools │  │
│  │ (读取工具)  │ │ (搜索工具) │ │ (监控工具)  │  │
│  └─────┬──────┘ └─────┬──────┘ └──────┬──────┘  │
│        │              │               │          │
│  ┌─────▼──────────────▼───────────────▼───────┐  │
│  │            Core Reader (核心读取层)          │  │
│  │  ┌──────────┐  ┌───────────┐  ┌─────────┐  │  │
│  │  │ Decryptor│  │ DB Router │  │ Contact │  │  │
│  │  │ (解密器)  │  │ (分片路由) │  │ Resolver│  │  │
│  │  └────┬─────┘  └─────┬─────┘  └────┬────┘  │  │
│  └───────┼──────────────┼──────────────┼───────┘  │
│          │              │              │          │
│  ┌───────▼──────────────▼──────────────▼───────┐  │
│  │          Key Manager (密钥管理)               │  │
│  │  ┌──────────────┐  ┌─────────────────────┐  │  │
│  │  │ all_keys.json│  │ Mach VM Key Finder  │  │  │
│  │  │ (密钥缓存)    │  │ (内存扫描提取)        │  │  │
│  │  └──────────────┘  └─────────────────────┘  │  │
│  └──────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────┘
                     │ SQLCipher
┌────────────────────▼────────────────────────────┐
│         WeChat Local Database (微信本地数据库)      │
│                                                  │
│  Message/msg_0.db ~ msg_N.db   (聊天消息)         │
│  Contact/wccontact_new2.db     (联系人)           │
│  Contact/group_new.db          (群聊信息)         │
│  Session/session.db            (会话列表)         │
└──────────────────────────────────────────────────┘
```

---

## 3. Technical Details

### 3.1 WeChat 数据库加密机制

微信使用 **WCDB (Tencent 开源 SQLCipher 封装)** 加密本地数据库：

| 参数 | 值 |
|------|-----|
| 加密算法 | AES-256-CBC |
| HMAC | HMAC-SHA512 |
| KDF | PBKDF2-HMAC-SHA512, 256,000 iterations |
| Page size | 4096 bytes |
| 密钥格式 | `x'<64 hex key><32 hex salt>'` (80 chars) |

源码参考: WCDB `CipherHandle.cpp` 的 `setCipherKey` 函数，
内部调用 `malloc(67)` 分配密钥缓冲区，密钥以 `UnsafeData` 结构体传递。

### 3.2 数据库位置 (macOS)

```
~/Library/Containers/com.tencent.xinWeChat/Data/
  Library/Application Support/com.tencent.xinWeChat/
    [version]/[uuid-hash]/
      Message/
        msg_0.db ~ msg_N.db     # 聊天消息 (按分片存储)
      Contact/
        wccontact_new2.db       # 联系人
        group_new.db            # 群聊信息
      Session/
        session.db              # 会话列表
```

#### 数据库表结构

**消息表** — 每个对话一张表 `Msg_<md5(username)>`:

| 列名 | 类型 | 说明 |
|------|------|------|
| local_id | INTEGER | 本地自增 ID |
| local_type | INTEGER | 消息类型 |
| create_time | INTEGER | 时间戳 (Unix seconds) |
| real_sender_id | TEXT | 实际发送者 ID |
| message_content | TEXT | 消息内容 |
| source | TEXT | 来源信息 |

**消息类型**:

| 类型码 | 含义 |
|--------|------|
| 1 | 文本 |
| 3 | 图片 |
| 34 | 语音 |
| 42 | 名片 |
| 43 | 视频 |
| 47 | 表情 |
| 48 | 位置 |
| 49 | 链接/文件/小程序 |
| 50 | 通话 |
| 10000 | 系统消息 |
| 10002 | 撤回消息 |

**联系人表** `contact` (wccontact_new2.db):

| 列名 | 说明 |
|------|------|
| username | 微信 ID (wxid_xxx) |
| remark | 备注名 |
| nick_name | 昵称 |

**会话表** `SessionTable` (session.db):

| 列名 | 说明 |
|------|------|
| username | 对话对象 ID |
| type | 会话类型 |
| summary | 最后一条消息摘要 |
| last_timestamp | 最后消息时间 |
| unread_count | 未读数 |

### 3.3 密钥提取方案

#### 方案对比

| 方案 | 需关闭 SIP | 实时性 | 推荐度 | 参考项目 |
|------|-----------|--------|--------|---------|
| **Mach VM 内存扫描** | 不需要 | WAL 轮询 ~100ms | 推荐 | ylytdeng/wechat-decrypt |
| LLDB 内存扫描 | 需要 | 查询级 | 备选 | Thearas/wechat-db-decrypt-macos |
| Frida 动态注入 | 需要 | 实时 | 不推荐 | — |
| DTrace 内核拦截 | 需要 | 实时 | 已被 DMCA | — |

#### 推荐方案: Mach VM API 内存扫描

```
WeChat 进程运行中
       │
  Mach VM API 扫描进程内存 (task_for_pid + vm_read)
       │
  正则匹配 x'([0-9a-fA-F]{64,192})' 模式
       │
  提取候选密钥 (32 bytes key + 16 bytes salt)
       │
  Salt 匹配验证 (与每个 .db 文件头 16 bytes 对比)
       │
  HMAC-SHA512 验证:
    mac_key = PBKDF2(enc_key, salt XOR 0x3A, iter=2, dklen=32)
    验证第一页 HMAC 正确性
       │
  输出 all_keys.json: { "db_path": "key_hex", ... }
```

#### 前置步骤 (一次性)

```bash
# 1. 重签名 WeChat (去掉 Hardened Runtime，允许内存读取)
sudo codesign --force --deep --sign - /Applications/WeChat.app

# 2. 编译内存扫描器 (C语言，依赖 Mach API)
xcode-select --install
cc -O2 -o find_all_keys_macos find_all_keys_macos.c -framework Foundation

# 3. 提取密钥 (需要 sudo，因为 task_for_pid 需要特权)
sudo ./find_all_keys_macos
# → 输出 all_keys.json
```

### 3.4 实时消息读取流程

```
用户: "提取 GPT-Runner 交流群今天有价值的内容"
         │
    Claude Code 调用 MCP Tool: wechat_read_group
         │
    ┌────▼──────────────────────────────────┐
    │  1. 加载已提取的密钥 (all_keys.json)    │
    │  2. 定位群聊:                          │
    │     group_new.db → 群名模糊搜索         │
    │     "GPT-Runner" → username           │
    │  3. 定位消息分片:                       │
    │     md5(username) → Msg_<hash> 表      │
    │     遍历 msg_0.db ~ msg_N.db 查找      │
    │  4. SQLCipher 解密 + WAL 合并          │
    │     PRAGMA key = "x'<key><salt>'"     │
    │  5. SQL 查询今天的消息:                  │
    │     WHERE create_time >= today_start   │
    │     AND local_type = 1 (文本)          │
    │  6. 解析发送者:                         │
    │     real_sender_id → contact 昵称/备注  │
    │  7. 返回格式化消息列表                    │
    └────┬──────────────────────────────────┘
         │
    Claude Code 分析内容价值 → 提取洞察
```

### 3.5 WAL 实时监控 (后台模式)

```python
# 监控 WAL 文件变化，实现准实时新消息检测
import os, time
from glob import glob

WAL_POLL_INTERVAL = 0.03  # 30ms

def watch_wal_files(db_dir: str):
    """监控微信 WAL 文件变化，yield 有新写入的 db 文件路径"""
    last_mtime = {}
    while True:
        for wal_file in glob(f"{db_dir}/msg_*.db-wal"):
            mtime = os.path.getmtime(wal_file)
            if wal_file not in last_mtime or mtime > last_mtime[wal_file]:
                last_mtime[wal_file] = mtime
                db_file = wal_file.replace("-wal", "")
                yield db_file  # 有新消息写入
        time.sleep(WAL_POLL_INTERVAL)
```

延迟: WAL 轮询 30ms + 解密查询 ~70ms = **总延迟约 100ms**

---

## 4. MCP Tools Design

### 聊天读取工具

```yaml
- name: wechat_read_group
  description: 实时读取微信群聊消息
  params:
    group_name: string     # 群名 (模糊匹配)
    date: string           # 日期，默认 today (YYYY-MM-DD 或 today/yesterday)
    keyword: string        # 关键词过滤 (可选)
    limit: int             # 返回数量 (默认 50)
  example: |
    用户: "提取 GPT-Runner 交流群今天有价值的内容"
    调用: wechat_read_group(group_name="GPT-Runner", date="today")

- name: wechat_read_chat
  description: 实时读取指定联系人的聊天记录
  params:
    contact_name: string   # 联系人名/备注名 (模糊匹配)
    date: string           # 日期或日期范围
    limit: int             # 默认 50

- name: wechat_sessions
  description: 查看最近聊天会话列表
  params:
    limit: int             # 默认 20
  returns: 会话列表 (名称、最后消息摘要、时间、未读数)
```

### 搜索工具

```yaml
- name: wechat_search
  description: 跨所有聊天全局搜索关键词
  params:
    keyword: string        # 搜索关键词
    group_only: bool       # 是否只搜群聊 (默认 false)
    date: string           # 时间范围 (可选)
    limit: int             # 默认 20

- name: wechat_contacts
  description: 搜索联系人和群聊
  params:
    query: string          # 模糊搜索 (昵称/备注名/群名)
    limit: int             # 默认 20
```

### 分析工具

```yaml
- name: wechat_extract_insights
  description: AI 分析群聊/对话的价值内容并提取洞察
  params:
    group_name: string     # 群名
    date: string           # 日期
    focus: string          # 关注方向 (可选，如 "技术讨论"/"行业动态"/"项目进展")
  returns: |
    结构化的洞察摘要:
    - 关键讨论话题
    - 有价值的观点/链接/资源
    - 行动项建议
```

### 监控工具

```yaml
- name: wechat_watch
  description: 后台监控指定群聊，检测新消息
  params:
    group_name: string     # 要监控的群名
    interval: int          # 检查间隔秒数 (默认 30)
  returns: 新消息列表 (自上次检查以来)

- name: wechat_new_messages
  description: 获取所有最新未读消息
  returns: 各会话的未读消息列表
```

### 管理工具

```yaml
- name: wechat_status
  description: 查看连接状态和数据库信息
  returns: |
    - 微信进程状态
    - 密钥状态 (已提取/需要更新)
    - 数据库文件列表和大小
    - 消息分片数量
    - 最近一条消息时间

- name: wechat_refresh_keys
  description: 重新提取微信数据库密钥
  returns: 新密钥数量和对应数据库
```

---

## 5. Tech Stack

| 组件 | 技术选型 | 理由 |
|------|---------|------|
| 语言 | Python 3.11+ | MCP SDK 支持好，SQLite 库成熟 |
| MCP 框架 | fastmcp | 轻量，ylytdeng/wechat-decrypt 已验证 |
| 加密数据库 | SQLCipher (via pysqlcipher3) | 直接读取加密 DB，无需导出 |
| 密钥提取 | C (Mach VM API) | task_for_pid + vm_read，无需关闭 SIP |
| 联系人匹配 | fuzzywuzzy / rapidfuzz | 模糊名称匹配 |
| 包管理 | uv | 快速，现代 Python 包管理 |

### 依赖说明

```toml
[project]
name = "wechat-mcp"
requires-python = ">=3.11"
dependencies = [
    "fastmcp>=2.0",
    "pysqlcipher3>=1.2",
    "rapidfuzz>=3.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

系统依赖:
- `brew install sqlcipher` — SQLCipher 库
- `xcode-select --install` — Xcode CLI Tools (编译密钥提取器)

---

## 6. Project Structure

```
wechat-mcp/
├── README.md
├── pyproject.toml
├── src/
│   └── wechat_mcp/
│       ├── __init__.py
│       ├── server.py           # MCP Server 入口 (fastmcp)
│       ├── reader.py           # 核心读取层: 解密 + 查询
│       ├── contacts.py         # 联系人/群聊解析和模糊匹配
│       ├── keys.py             # 密钥管理 (加载/验证/刷新)
│       ├── watcher.py          # WAL 文件监控 (后台模式)
│       └── types.py            # 数据类型定义
├── tools/
│   ├── find_all_keys_macos.c   # Mach VM 密钥提取器 (C)
│   ├── build_key_finder.sh     # 编译脚本
│   └── setup.sh                # 一键初始化 (重签名 + 编译 + 提取密钥)
├── config/
│   └── default.yaml            # 默认配置
├── docs/
│   └── plans/
│       └── 2026-03-06-wechat-mcp-design.md
└── tests/
    ├── test_reader.py
    ├── test_contacts.py
    └── test_keys.py
```

---

## 7. Claude Code Integration

### 配置方式

```json
// ~/.claude.json
{
  "mcpServers": {
    "wechat": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/wechat-mcp", "python", "-m", "wechat_mcp.server"],
      "transport": "stdio"
    }
  }
}
```

### 使用示例

```
用户: 提取 GPT-Runner 交流群今天有价值的内容帮助你进化

Claude Code:
  1. 调用 wechat_read_group(group_name="GPT-Runner", date="today")
  2. 获取今天的群聊消息
  3. 分析消息内容，提取有价值的讨论:
     - 技术方案讨论
     - 有用的链接和资源
     - 关键决策和结论
  4. 将洞察写入 knowledge/ 目录 (ai-rag 项目)
  5. 自动 git commit 记录进化
```

---

## 8. Security & Compliance

### 红线原则

> **绝不允许调用微信的任何网络请求接口。违反此原则可能导致微信账号被封。**

本项目**仅读取本地 SQLite 数据库文件**，与微信网络协议零交互：
- 不调用微信 HTTP/WebSocket API
- 不模拟微信客户端协议
- 不注入微信进程发送请求
- 不 Hook 微信网络层
- 不使用 Accessibility API 模拟操作微信 UI
- 不发送消息、不修改聊天、不触发任何微信服务器可感知的行为

**唯一的数据来源**: 读取硬盘上已存在的 `.db` 文件 (SQLCipher 加密的 SQLite)

### 本地安全

- 所有数据**仅在本地处理**，不上传任何服务器
- 密钥仅存储在本地 `all_keys.json`，必须 `.gitignore`
- 微信需要保持登录状态（密钥在进程内存中）
- MCP Server 仅支持**只读**操作
- 不修改微信数据库文件

### 法律风险提示

- Tencent 已对多个类似项目发送 DMCA/律师函:
  - PyWxDump (2025.10) — 代码已删除
  - chatlog (2025.10) — 被迫删库
  - wechat-decipher-macos (2026.01)
- 建议: 仅用于个人数据管理，及时 fork 关键依赖项目
- 本项目不分发微信逆向工具，仅提供 MCP 集成层

---

## 9. Roadmap

### Phase 1: Core Reading (Week 1)
- [ ] 集成 ylytdeng/wechat-decrypt 密钥提取器
- [ ] 实现 `reader.py`: SQLCipher 解密 + 消息查询
- [ ] 实现 `contacts.py`: 联系人/群聊模糊匹配
- [ ] MCP Server: `wechat_read_group` + `wechat_read_chat` + `wechat_sessions`
- [ ] `setup.sh` 一键初始化脚本

### Phase 2: Search & Analysis (Week 2)
- [ ] `wechat_search`: 跨聊天全局搜索
- [ ] `wechat_contacts`: 联系人搜索
- [ ] `wechat_extract_insights`: AI 价值内容提取
- [ ] `wechat_status`: 连接状态检查

### Phase 3: Real-time Monitoring (Week 3)
- [ ] `watcher.py`: WAL 文件监控
- [ ] `wechat_watch`: 后台监控指定群聊
- [ ] `wechat_new_messages`: 新消息检测
- [ ] `wechat_refresh_keys`: 密钥刷新

### Phase 4: Hardening (Week 4)
- [ ] 错误处理和重试机制
- [ ] 密钥自动刷新 (微信重启后)
- [ ] 多账号支持
- [ ] 消息缓存优化
- [ ] 完整测试覆盖

---

## 10. References

### 核心参考项目
- [ylytdeng/wechat-decrypt](https://github.com/ylytdeng/wechat-decrypt) — Mach VM 内存扫描 + MCP Server，无需关闭 SIP
- [Thearas/wechat-db-decrypt-macos](https://github.com/Thearas/wechat-db-decrypt-macos) — LLDB 内存扫描 + MCP Server (177 stars)
- [WeChat-MCP](https://github.com/BiboyQG/WeChat-MCP) — Accessibility API 方式，可读可发

### 数据库逆向参考
- WCDB 源码: `CipherHandle.cpp` → `setCipherKey` 函数
- SQLCipher: PRAGMA key 格式 `x'<hex_key><hex_salt>'`
- WeChat 消息分片: msg_0.db ~ msg_N.db，每个对话独立表

### 关联项目
- [ai-rag](https://github.com/zzanzifeng/ai-rag) — AI RAG 知识库，本项目作为数据源之一
