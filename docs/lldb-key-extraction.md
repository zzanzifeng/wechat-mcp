# 微信 SQLCipher 密钥提取指南

## 概述

微信 macOS 版使用 WCDB（基于 SQLCipher）加密本地聊天数据库。所有 `.db` 文件在打开时需要传入 32 字节密钥。本文档记录通过 LLDB 调试器提取该密钥的完整方法。

## 原理

微信启动并登录后，会调用 WCDB 框架的 `sqlite3_key()` 函数为每个数据库设置解密密钥：

```c
// 函数签名
int sqlite3_key(sqlite3 *db, const void *key, int key_len);
```

在 ARM64 (Apple Silicon) 的调用约定中，参数通过寄存器传递：

| 寄存器 | 参数 | 说明 |
|--------|------|------|
| `x0` | `sqlite3 *db` | 数据库句柄 |
| `x1` | `const void *key` | **密钥指针** |
| `x2` | `int key_len` | 密钥长度（通常为 `0x20` = 32 字节） |

在函数入口处设断点，即可从 `x1` 指向的内存读取密钥。

## 前置条件

- macOS（Apple Silicon 或 Intel）
- WeChat for Mac 已安装
- Xcode Command Line Tools（提供 `lldb`）
- **需要先退出正在运行的微信**

> **注意**: macOS 可能需要关闭 SIP 或对 lldb 授予调试权限。如果遇到权限问题，参考 [疑难排解](#疑难排解) 章节。

## 方式一：自动化脚本（推荐）

### 一键执行

```bash
./scripts/extract_wechat_key.sh
```

脚本会：
1. 检查微信是否正在运行
2. 通过 LLDB 启动微信并加载 Python 提取脚本
3. 在 `sqlite3_key` 设断点
4. 登录后自动捕获并打印密钥

### 脚本内自定义命令

微信登录后，在 LLDB 交互界面中可使用：

```
(lldb) print_keys    # 打印所有捕获的密钥
(lldb) save_keys     # 保存到 ~/.wechat_keys/
```

## 方式二：手动 LLDB 操作

### Step 1: 启动 LLDB

```bash
lldb /Applications/WeChat.app/Contents/MacOS/WeChat
```

### Step 2: 设置断点

```
(lldb) br set -n sqlite3_key
Breakpoint 1: 2 locations.
```

### Step 3: 运行微信

```
(lldb) run
```

等待微信窗口出现，完成登录（扫码/手机确认）。

### Step 4: 断点命中后读取密钥

登录后 LLDB 会暂停在断点处：

```
Process XXXXX stopped
* thread #1, stop reason = breakpoint 1.1
    frame #0: 0x... WCDB`sqlite3_key
```

确认密钥长度：

```
(lldb) register read x2
      x2 = 0x0000000000000020    # 32 字节
```

读取密钥（字节序）：

```
(lldb) memory read --size 1 --format x --count 32 $x1
```

输出示例：

```
0x7001e91280: 0xad 0xb0 0x9e 0xc6 0x49 0xe9 0x43 0xb2
0x7001e91288: 0xa1 0xe4 0x17 0xa9 0x61 0xf3 0x1d 0x28
0x7001e91290: 0x0f 0xe6 0x17 0x37 0xa0 0x35 0x46 0x90
0x7001e91298: 0xac 0x6b 0x1a 0xf6 0xa9 0xb8 0x41 0xe0
```

### Step 5: 拼接密钥

将输出拼接为完整 hex 字符串：

```
0xadb09ec649e943b2a1e417a961f31d280fe61737a0354690ac6b1af6a9b841e0
```

### Step 6: 继续执行或退出

```
(lldb) c        # 继续执行微信（会再次命中断点）
(lldb) exit     # 退出 LLDB（微信进程也会终止）
```

## 使用提取的密钥

### 配置 decrypt_wechat_db.py

将密钥填入 `decrypt_wechat_db.py`：

```python
RAW_KEY_HEX = "adb09ec649e943b2a1e417a961f31d280fe61737a0354690ac6b1af6a9b841e0"
```

然后执行解密：

```bash
python3 decrypt_wechat_db.py
```

### 密钥格式说明

| 格式 | 长度 | 说明 |
|------|------|------|
| `sqlite3_key` 原始密钥 | 32 字节 | 从 LLDB 提取的原始格式 |
| WCDB `sqlite3_key_raw` 格式 | 46 字节 | 带 `cafecafe` 前缀的内部格式 |

`sqlite3_key` 接收 32 字节原始密钥后，WCDB 内部会自动处理密钥派生。使用 Python ctypes 调用时，直接传 32 字节密钥给 `sqlite3_key` 即可。

## 注意事项

- **密钥与账户绑定** — 每个微信账户的密钥不同，切换账户后需要重新提取
- **密钥可能更新** — 微信大版本更新后密钥可能变化
- **断点会命中多次** — 微信会依次打开多个数据库，所有数据库使用相同密钥
- **WCDB vs SQLCipher** — 微信使用的是 WCDB 定制版 SQLCipher，加密参数与标准 SQLCipher 不同，需用微信自带的 WCDB 框架解密

## 疑难排解

### lldb 报错 "unable to attach"

macOS 默认限制调试非自己构建的应用。解决方案：

```bash
# 方案1: 用 lldb 直接启动（而非附加），即本文档的方法
lldb /Applications/WeChat.app/Contents/MacOS/WeChat

# 方案2: 如需附加到运行中的进程
sudo lldb -p $(pgrep WeChat)
```

### 断点不命中

确认 WCDB 框架已加载：

```
(lldb) image list WCDB
```

如果为空，说明微信尚未加载 WCDB，等待登录流程推进。

### Intel Mac 寄存器差异

Intel (x86_64) 使用不同的寄存器：

```
(lldb) register read rsi    # key 指针 (第二个参数)
(lldb) register read rdx    # key 长度 (第三个参数)
(lldb) memory read --size 1 --format x --count 32 $rsi
```

## 参考

- [WCDB - 微信开源数据库框架](https://github.com/nicklockwood/iCarousel)
- [SQLCipher](https://www.zetetic.net/sqlcipher/)
- LLDB 文档: `help memory read`, `help breakpoint set`
