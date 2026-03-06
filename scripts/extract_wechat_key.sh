#!/usr/bin/env bash
# 一键提取微信 SQLCipher 密钥
#
# 用法: ./extract_wechat_key.sh
#
# 原理: 通过 LLDB 附加微信进程，在 sqlite3_key 设断点，
#       从 ARM64 寄存器 x1 (key指针) 和 x2 (key长度) 读取密钥。

set -euo pipefail

WECHAT_APP="/Applications/WeChat.app/Contents/MacOS/WeChat"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
KEY_FILE="$HOME/.wechat_keys/wechat_key_$(date +%Y%m%d_%H%M%S).txt"

if [ ! -f "$WECHAT_APP" ]; then
    echo "错误: 未找到微信应用 ($WECHAT_APP)"
    exit 1
fi

# 检查微信是否正在运行
if pgrep -x WeChat > /dev/null 2>&1; then
    echo "警告: 微信正在运行，请先退出微信再执行此脚本"
    echo "  执行: pkill WeChat"
    exit 1
fi

echo "================================"
echo "  WeChat SQLCipher 密钥提取"
echo "================================"
echo ""
echo "即将通过 LLDB 启动微信..."
echo "请在微信窗口中完成登录，密钥会在登录后自动提取。"
echo ""

# 使用 Python 脚本模式
if [ -f "$SCRIPT_DIR/extract_wechat_key.py" ]; then
    echo "使用 Python 自动化脚本..."
    lldb \
        -o "command script import $SCRIPT_DIR/extract_wechat_key.py" \
        -o "run" \
        "$WECHAT_APP"
else
    # 纯 LLDB 命令模式 (手动)
    echo "使用手动 LLDB 命令模式..."
    echo ""
    echo "LLDB 启动后请依次执行:"
    echo "  (lldb) br set -n sqlite3_key"
    echo "  (lldb) run"
    echo "  [登录微信, 等待断点命中]"
    echo "  (lldb) memory read --size 1 --format x --count 32 \$x1"
    echo "  (lldb) register read x2   # 确认密钥长度"
    echo ""
    lldb "$WECHAT_APP"
fi
