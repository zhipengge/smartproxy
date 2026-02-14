"""
代理应用管理：为指定应用生成经代理启动的脚本，其他应用默认直连
"""

import os
import shutil
from pathlib import Path
from typing import List, Optional


BIN_DIR = Path.home() / ".local/bin"
APPS_DIR = Path.home() / ".config/smartproxy"  # 用 XDG
XDG_APPS = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "applications"
PROXYCHAIN_CONF = Path.home() / ".config/smartproxy/proxychains.conf"
# 代理应用直连 SSH 隧道 1080，确保 Telegram 等兼容性
PROXY = "socks5://127.0.0.1:1080"


def _has_proxychains() -> Optional[str]:
    for cmd in ("proxychains4", "proxychains"):
        if shutil.which(cmd):
            return cmd
    return None


def generate_launcher(name: str, exec_cmd: str, desktop_name: str) -> tuple[str, str]:
    """
    生成代理启动脚本和桌面快捷方式。
    返回 (bin_path, desktop_path)，失败抛异常。
    """
    name = name.strip().lower().replace(" ", "-")
    if not name or not exec_cmd.strip():
        raise ValueError("name 和 exec 不能为空")
    desktop_name = desktop_name.strip() or name.title()

    # Telegram 单实例：经代理需用 -many -workdir 强制独立实例，否则会激活已有（未代理）窗口
    if "telegram" in name:
        workdir = str(Path.home() / ".local/share/telegram-via-proxy")
        Path(workdir).mkdir(parents=True, exist_ok=True)
        if exec_cmd.strip().startswith("flatpak run"):
            exec_cmd = exec_cmd.strip() + f" -- -many -workdir {workdir}"
        else:
            exec_cmd = exec_cmd.strip() + f" -many -workdir {workdir}"

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    XDG_APPS.mkdir(parents=True, exist_ok=True)
    PROXYCHAIN_CONF.parent.mkdir(parents=True, exist_ok=True)

    bin_path = BIN_DIR / f"{name}-via-proxy"
    desktop_path = XDG_APPS / f"{name}-via-proxy.desktop"  # 文件名用 name 便于删除

    pc = _has_proxychains()
    if pc:
        # 使用 1080 (SSH 隧道) 直连，避免经 SmartProxy 1081 时的兼容性问题
        PROXYCHAIN_CONF.write_text(f"""strict_chain
proxy_dns
[ProxyList]
socks5 127.0.0.1 1080
""")
        script = f"""#!/bin/bash
exec {pc} -f {PROXYCHAIN_CONF} {exec_cmd} "$@"
"""
    else:
        script = f"""#!/bin/bash
export ALL_PROXY="{PROXY}"
export all_proxy="{PROXY}"
        export HTTPS_PROXY="http://127.0.0.1:8080"
        export HTTP_PROXY="http://127.0.0.1:8080"
exec {exec_cmd} "$@"
"""

    bin_path.write_text(script)
    bin_path.chmod(0o755)

    icon = "telegram" if "telegram" in name else "applications-internet"
    desktop_content = f"""[Desktop Entry]
Name={desktop_name} (经代理)
Exec={bin_path}
Icon={icon}
Type=Application
Categories=Network;
"""
    desktop_path.write_text(desktop_content)

    return str(bin_path), str(desktop_path)


def remove_launcher(name: str, desktop_name: str = "") -> bool:
    """删除代理启动脚本和桌面快捷方式"""
    name = name.strip().lower().replace(" ", "-")
    bin_path = BIN_DIR / f"{name}-via-proxy"
    desktop_path = XDG_APPS / f"{name}-via-proxy.desktop"  # 文件名与 name 一致
    removed = False
    if bin_path.exists():
        bin_path.unlink()
        removed = True
    if desktop_path.exists():
        desktop_path.unlink()
        removed = True
    return removed
