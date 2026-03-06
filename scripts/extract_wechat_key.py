#!/usr/bin/env python3
"""
LLDB 自动提取微信 SQLCipher 密钥脚本

用法:
  方式一 (LLDB 内加载):
    lldb /Applications/WeChat.app/Contents/MacOS/WeChat
    (lldb) command script import /path/to/extract_wechat_key.py
    (lldb) run

  方式二 (命令行一键执行):
    lldb -o "command script import /path/to/extract_wechat_key.py" -o run \
         /Applications/WeChat.app/Contents/MacOS/WeChat

原理:
  在 WCDB 的 sqlite3_key 上设断点，命中时从 ARM64 寄存器读取:
    x0 = sqlite3* db
    x1 = const void* key  (密钥指针)
    x2 = int key_len      (密钥长度，通常 32)
"""

import lldb
import os
import datetime

KEY_OUTPUT_DIR = os.path.expanduser("~/.wechat_keys")
WECHAT_APP = "/Applications/WeChat.app/Contents/MacOS/WeChat"

# 收集到的所有密钥 (去重)
_collected_keys = set()
_first_key = None


def on_sqlite3_key_hit(frame, bp_loc, dict):
    """sqlite3_key 断点回调: 从寄存器读取密钥"""
    global _first_key

    thread = frame.GetThread()
    process = thread.GetProcess()

    # ARM64 调用约定: x0=db, x1=key_ptr, x2=key_len
    key_ptr = frame.FindRegister("x1").GetValueAsUnsigned()
    key_len = frame.FindRegister("x2").GetValueAsUnsigned()

    if key_len == 0 or key_ptr == 0:
        return False  # 继续执行

    # 从内存读取密钥
    error = lldb.SBError()
    key_data = process.ReadMemory(key_ptr, key_len, error)

    if error.Fail():
        print(f"[extract_key] 读取内存失败: {error.GetCString()}")
        return False

    key_hex = key_data.hex()

    if key_hex in _collected_keys:
        return False  # 已收集过，跳过

    _collected_keys.add(key_hex)

    if _first_key is None:
        _first_key = key_hex

    # 尝试获取数据库路径 (从调用栈推断)
    db_hint = _get_db_hint(thread)

    print(f"\n{'='*60}")
    print(f"[extract_key] 捕获到 SQLCipher 密钥!")
    print(f"  长度: {key_len} bytes")
    print(f"  HEX:  0x{key_hex}")
    if db_hint:
        print(f"  数据库: {db_hint}")
    print(f"  已收集密钥数: {len(_collected_keys)}")
    print(f"{'='*60}\n")

    return False  # False = 自动继续执行


def _get_db_hint(thread):
    """尝试从调用栈获取数据库路径提示"""
    for i in range(min(thread.GetNumFrames(), 10)):
        frame = thread.GetFrameAtIndex(i)
        fn = frame.GetFunctionName()
        if fn and "setCipherKey" in fn:
            return fn
    return None


def save_keys(debugger, command, result, dict):
    """保存所有收集到的密钥到文件

    用法: (lldb) save_keys
    """
    if not _collected_keys:
        result.AppendMessage("未收集到任何密钥。请先运行 WeChat 并等待断点命中。")
        return

    os.makedirs(KEY_OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(KEY_OUTPUT_DIR, f"wechat_key_{timestamp}.txt")

    with open(output_file, "w") as f:
        f.write(f"# WeChat SQLCipher Keys - {timestamp}\n")
        f.write(f"# 提取方式: LLDB breakpoint on sqlite3_key\n\n")
        for i, key in enumerate(sorted(_collected_keys), 1):
            f.write(f"key_{i}=0x{key}\n")
        f.write(f"\n# 用于 decrypt_wechat_db.py 的格式:\n")
        f.write(f"# RAW_KEY_HEX = \"{sorted(_collected_keys)[0]}\"\n")

    result.AppendMessage(f"已保存 {len(_collected_keys)} 个密钥到: {output_file}")


def print_keys(debugger, command, result, dict):
    """打印所有已收集的密钥

    用法: (lldb) print_keys
    """
    if not _collected_keys:
        result.AppendMessage("未收集到任何密钥。")
        return

    result.AppendMessage(f"\n已收集 {len(_collected_keys)} 个密钥:")
    for i, key in enumerate(sorted(_collected_keys), 1):
        result.AppendMessage(f"  key_{i} = 0x{key}")

    result.AppendMessage(f"\n用于 Python 脚本:")
    result.AppendMessage(f'  RAW_KEY_HEX = "{sorted(_collected_keys)[0]}"')


def __lldb_init_module(debugger, dict):
    """LLDB 加载模块时自动执行"""
    # 注册自定义命令
    debugger.HandleCommand(
        'command script add -f extract_wechat_key.save_keys save_keys'
    )
    debugger.HandleCommand(
        'command script add -f extract_wechat_key.print_keys print_keys'
    )

    # 在 sqlite3_key 上设断点 (不限定模块，兼容新旧版本微信)
    # 旧版: 符号在 WCDB 框架内
    # 新版: 符号可能在 libsqlite3.dylib 或其他位置
    debugger.HandleCommand(
        'breakpoint set -n sqlite3_key'
    )

    target = debugger.GetSelectedTarget()
    if target:
        bp = target.GetBreakpointAtIndex(target.GetNumBreakpoints() - 1)
        bp.SetScriptCallbackFunction("extract_wechat_key.on_sqlite3_key_hit")

    # 备用: setCipherKey (WCDB 调用 sqlite3_key 的上层函数)
    debugger.HandleCommand(
        'breakpoint set -r setCipherKey'
    )
    if target and target.GetNumBreakpoints() > 1:
        bp2 = target.GetBreakpointAtIndex(target.GetNumBreakpoints() - 1)
        bp2.SetScriptCallbackFunction("extract_wechat_key.on_sqlite3_key_hit")

    print(f"""
{'='*60}
  WeChat SQLCipher 密钥提取脚本已加载

  断点已设置: sqlite3_key
  等待 WeChat 启动并打开数据库...

  自定义命令:
    print_keys  — 打印已收集的密钥
    save_keys   — 保存密钥到 ~/.wechat_keys/

  提示: 登录微信后密钥会自动捕获并打印
{'='*60}
""")
