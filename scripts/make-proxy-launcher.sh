#!/bin/bash
# 为不跟随系统代理的应用生成带代理启动的脚本/桌面快捷方式
# 用法: ./make-proxy-launcher.sh [telegram|discord|...]
# 自定义可执行文件: ./make-proxy-launcher.sh telegram "flatpak run org.telegram.desktop"

PROXY="${SMARTPROXY_SOCKS5:-socks5://127.0.0.1:1080}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
BIN_DIR="${HOME}/.local/bin"

mkdir -p "$BIN_DIR" "$APPS_DIR"

gen_launcher() {
    local name="$1"
    local exec_cmd="$2"
    local desktop_name="$3"
    
    # 生成启动脚本（通过环境变量，部分应用支持）
    cat > "$BIN_DIR/${name}-via-proxy" << EOF
#!/bin/bash
export ALL_PROXY="$PROXY"
export all_proxy="$PROXY"
export HTTPS_PROXY="http://127.0.0.1:8080"
export HTTP_PROXY="http://127.0.0.1:8080"
exec $exec_cmd "\$@"
EOF
    chmod +x "$BIN_DIR/${name}-via-proxy"
    
    # 若 proxychains 可用，生成更可靠的版本
    PROXYCHAIN_BIN=""
    command -v proxychains4 &>/dev/null && PROXYCHAIN_BIN="proxychains4"
    command -v proxychains &>/dev/null && [ -z "$PROXYCHAIN_BIN" ] && PROXYCHAIN_BIN="proxychains"
    if [ -n "$PROXYCHAIN_BIN" ]; then
        PROXYCHAIN_CONF="$HOME/.config/smartproxy/proxychains.conf"
        mkdir -p "$(dirname "$PROXYCHAIN_CONF")"
        echo "strict_chain
proxy_dns
[ProxyList]
socks5 127.0.0.1 1080" > "$PROXYCHAIN_CONF"
        cat > "$BIN_DIR/${name}-via-proxy" << EOF
#!/bin/bash
exec $PROXYCHAIN_BIN -f $PROXYCHAIN_CONF $exec_cmd "\$@"
EOF
        chmod +x "$BIN_DIR/${name}-via-proxy"
    fi
    
    # 桌面快捷方式
    cat > "$APPS_DIR/${desktop_name}-via-proxy.desktop" << EOF
[Desktop Entry]
Name=${desktop_name} (经代理)
Exec=$BIN_DIR/${name}-via-proxy
Icon=telegram
Type=Application
Categories=Network;
EOF
    
    echo "✅ 已生成: $BIN_DIR/${name}-via-proxy"
    echo "✅ 桌面快捷: $APPS_DIR/${desktop_name}-via-proxy.desktop"
    echo "   运行: ${name}-via-proxy 或从应用菜单启动「${desktop_name} (经代理)」"
}

find_telegram() {
    # Snap
    [ -x /snap/bin/telegram-desktop ] && echo "/snap/bin/telegram-desktop" && return
    # Flatpak
    flatpak list --app 2>/dev/null | grep -q org.telegram.desktop && echo "flatpak run org.telegram.desktop" && return
    # PATH
    command -v telegram-desktop &>/dev/null && echo "telegram-desktop" && return
    command -v telegram &>/dev/null && echo "telegram" && return
    # 默认（用户可手动改）
    echo "telegram-desktop"
}

case "${1:-telegram}" in
    telegram)
        EXEC="${2:-$(find_telegram)}"
        if [ "$EXEC" = "telegram-desktop" ] && ! command -v telegram-desktop &>/dev/null && [ ! -x /snap/bin/telegram-desktop ]; then
            echo "⚠️ 未检测到 telegram-desktop"
            echo "   若通过 Flatpak 安装，请运行: $0 telegram 'flatpak run org.telegram.desktop'"
            echo "   或手动编辑 ~/.local/bin/telegram-via-proxy 中的可执行命令"
        fi
        gen_launcher "telegram" "$EXEC" "Telegram"
        ;;
    discord)
        gen_launcher "discord" "discord" "Discord"
        ;;
    *)
        echo "用法: $0 [telegram|discord]"
        echo "或: SMARTPROXY_SOCKS5=socks5://127.0.0.1:1081 $0 telegram"
        exit 1
        ;;
esac

echo ""
echo "💡 若应用仍无法连接，请安装 proxychains-ng: sudo apt install proxychains4"
