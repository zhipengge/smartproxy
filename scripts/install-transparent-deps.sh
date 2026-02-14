#!/bin/bash
# 透明代理系统依赖安装脚本
# 在项目安装时运行，而非 app 启动时
# 用法: sudo ./install-transparent-deps.sh

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "请使用 sudo 运行: sudo $0"
    exit 1
fi

echo "=== 安装透明代理系统依赖 ==="
apt-get update -qq
apt-get install -y redsocks
echo ""
echo "✅ redsocks 已安装"
echo "   启用透明代理: sudo scripts/setup-transparent-proxy.sh enable"
echo "   或在 Web 界面使用透明代理开关"
