#!/bin/bash
# 透明代理一键配置脚本
# 用法: sudo ./setup-transparent-proxy.sh [enable|disable]

REDSOCKS_CONF="/etc/redsocks.conf"
REDSOCKS_PORT=12345
SMARTPROXY_SOCKS_PORT=1081

if [ "$(id -u)" -ne 0 ]; then
    echo "请使用 sudo 运行: sudo $0 enable"
    exit 1
fi

case "${1:-}" in
    enable)
        if ! command -v redsocks >/dev/null 2>&1; then
            echo "错误: 未找到 redsocks"
            echo "请先运行: sudo scripts/install-transparent-deps.sh"
            exit 1
        fi
        
        echo "=== 1. 配置 redsocks ==="
        cat > "$REDSOCKS_CONF" << EOF
base {
    log_debug = off;
    log_info = on;
    log = "file:/tmp/redsocks.log";
    daemon = on;
    redirector = iptables;
}

redsocks {
    local_ip = 127.0.0.1;
    local_port = $REDSOCKS_PORT;
    ip = 127.0.0.1;
    port = $SMARTPROXY_SOCKS_PORT;
    type = socks5;
}
EOF
        echo "已写入 $REDSOCKS_CONF"
        
        echo "=== 2. 配置 iptables ==="
        iptables -t nat -F OUTPUT 2>/dev/null
        iptables -t nat -F REDSOCKS 2>/dev/null
        iptables -t nat -X REDSOCKS 2>/dev/null
        
        iptables -t nat -N REDSOCKS
        iptables -t nat -A REDSOCKS -d 0.0.0.0/8 -j RETURN
        iptables -t nat -A REDSOCKS -d 10.0.0.0/8 -j RETURN
        iptables -t nat -A REDSOCKS -d 127.0.0.0/8 -j RETURN
        iptables -t nat -A REDSOCKS -d 169.254.0.0/16 -j RETURN
        iptables -t nat -A REDSOCKS -d 172.16.0.0/12 -j RETURN
        iptables -t nat -A REDSOCKS -d 192.168.0.0/16 -j RETURN
        iptables -t nat -A REDSOCKS -d 224.0.0.0/4 -j RETURN
        iptables -t nat -A REDSOCKS -d 240.0.0.0/4 -j RETURN
        iptables -t nat -A REDSOCKS -p tcp -j REDIRECT --to-ports $REDSOCKS_PORT
        iptables -t nat -A OUTPUT -p tcp -j REDSOCKS
        
        echo "=== 3. 启动 redsocks ==="
        systemctl restart redsocks
        systemctl enable redsocks 2>/dev/null
        
        # 更新 config 避免连接回环（需以实际用户运行以找到正确 config 路径）
        if [ -n "$SUDO_USER" ]; then
            SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
            if [ -f "$SCRIPT_DIR/app.py" ]; then
                (cd "$SCRIPT_DIR" && sudo -u "$SUDO_USER" PYTHONPATH="$SCRIPT_DIR" python3 -c "
from smartproxy.config import Config
c = Config()
c.set('transparent_proxy.force_all_via_upstream', True)
print('已设置 force_all_via_upstream')
" 2>/dev/null) || true
            fi
        fi
        echo ""
        echo "✅ 透明代理已启用"
        echo "   全部流量经 VPS 转发（避免连接回环），国内站点可能稍慢"
        echo "   若 SmartProxy 已在运行，请重启 (Ctrl+C 后重新 python app.py) 使配置生效"
        echo "   撤销: sudo $0 disable"
        ;;
    disable)
        echo "=== 撤销透明代理 ==="
        if [ -n "$SUDO_USER" ]; then
            SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
            if [ -f "$SCRIPT_DIR/app.py" ]; then
                (cd "$SCRIPT_DIR" && sudo -u "$SUDO_USER" PYTHONPATH="$SCRIPT_DIR" python3 -c "
from smartproxy.config import Config
c = Config()
c.set('transparent_proxy.force_all_via_upstream', False)
" 2>/dev/null) || true
            fi
        fi
        iptables -t nat -F OUTPUT 2>/dev/null
        iptables -t nat -F REDSOCKS 2>/dev/null
        iptables -t nat -X REDSOCKS 2>/dev/null
        systemctl stop redsocks 2>/dev/null
        echo "✅ 已恢复直连"
        ;;
    *)
        echo "用法: sudo $0 enable   # 启用透明代理"
        echo "      sudo $0 disable # 撤销"
        exit 1
        ;;
esac
