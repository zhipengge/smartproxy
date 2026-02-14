"""
透明代理自动化：redsocks + iptables
需 root 权限运行
"""

import os
import shutil
import subprocess
import sys


REDSOCKS_CONF = "/etc/redsocks.conf"
REDSOCKS_PORT = 12345
SMARTPROXY_SOCKS_PORT = 1081


def _is_root() -> bool:
    return os.geteuid() == 0


def _run(cmd: list, check: bool = True) -> bool:
    try:
        subprocess.run(cmd, check=check, capture_output=not check)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def setup_enable() -> bool:
    """启用透明代理，需 root"""
    if not _is_root():
        print("透明代理需要 root，请使用: sudo python app.py")
        return False
    if sys.platform != "linux":
        print("透明代理仅支持 Linux")
        return False

    print("\n=== 透明代理配置 ===")
    # 1. 检查 redsocks（需在项目安装时运行 scripts/install-transparent-deps.sh）
    if shutil.which("redsocks") is None:
        print("未找到 redsocks，请先运行: sudo scripts/install-transparent-deps.sh")
        return False
    # 2. 配置
    conf = f"""base {{
    log_debug = off;
    log_info = on;
    log = "file:/tmp/redsocks.log";
    daemon = on;
    redirector = iptables;
}}

redsocks {{
    local_ip = 127.0.0.1;
    local_port = {REDSOCKS_PORT};
    ip = 127.0.0.1;
    port = {SMARTPROXY_SOCKS_PORT};
    type = socks5;
}}
"""
    with open(REDSOCKS_CONF, "w") as f:
        f.write(conf)
    print("已写入", REDSOCKS_CONF)
    # 3. iptables
    print("配置 iptables...")
    rules = [
        ["iptables", "-t", "nat", "-F", "OUTPUT"],
        ["iptables", "-t", "nat", "-F", "REDSOCKS"],
        ["iptables", "-t", "nat", "-X", "REDSOCKS"],
        ["iptables", "-t", "nat", "-N", "REDSOCKS"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "0.0.0.0/8", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "10.0.0.0/8", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "127.0.0.0/8", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "169.254.0.0/16", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "172.16.0.0/12", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "192.168.0.0/16", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "224.0.0.0/4", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-d", "240.0.0.0/4", "-j", "RETURN"],
        ["iptables", "-t", "nat", "-A", "REDSOCKS", "-p", "tcp", "-j", "REDIRECT", "--to-ports", str(REDSOCKS_PORT)],
        ["iptables", "-t", "nat", "-A", "OUTPUT", "-p", "tcp", "-j", "REDSOCKS"],
    ]
    for r in rules:
        subprocess.run(r, capture_output=True)  # 忽略已存在等错误
    # 4. 持久化 iptables（如有 netfilter-persistent）
    _run(["netfilter-persistent", "save"], check=False)
    _run(["iptables-save"], check=False)
    # 5. 启动 redsocks
    _run(["systemctl", "restart", "redsocks"])
    _run(["systemctl", "enable", "redsocks"], check=False)
    print("✅ 透明代理已启用（所有应用自动走 SmartProxy）")
    return True


def setup_disable() -> bool:
    """撤销透明代理"""
    if not _is_root():
        return False
    subprocess.run(["iptables", "-t", "nat", "-F", "OUTPUT"], capture_output=True)
    subprocess.run(["iptables", "-t", "nat", "-F", "REDSOCKS"], capture_output=True)
    subprocess.run(["iptables", "-t", "nat", "-X", "REDSOCKS"], capture_output=True)
    subprocess.run(["systemctl", "stop", "redsocks"], capture_output=True)
    _run(["netfilter-persistent", "save"], check=False)
    print("✅ 透明代理已撤销")
    return True


def ensure_transparent_proxy() -> bool:
    """
    确保透明代理已启用。若当前无 root，尝试通过 sudo 执行。
    """
    if _is_root() and sys.platform == "linux":
        return setup_enable()
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    setup_script = os.path.join(script_dir, "scripts", "setup-transparent-proxy.sh")
    if os.path.exists(setup_script):
        r = subprocess.run(["sudo", "bash", setup_script, "enable"])
        return r.returncode == 0
    return False
