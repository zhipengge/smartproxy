"""
SmartProxy - 智能流量分析工具
基于 Flask 的 Web 管理界面
"""

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO
from flask_cors import CORS
import json
import os
import subprocess
import sys
from pathlib import Path
import threading
import time
from datetime import datetime

from smartproxy.core import SmartProxyCore
from smartproxy.config import Config
from smartproxy.proxy_server import run_proxy_server, run_socks5_proxy_server

# 创建 Flask 应用
app = Flask(__name__, 
    template_folder='templates',
    static_folder='static')
app.config['SECRET_KEY'] = os.urandom(24)

# 启用 CORS 和 SocketIO
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# 创建核心实例
config = Config()
proxy = SmartProxyCore(config)

# 背景任务：更新状态
def background_monitor():
    """后台监控状态"""
    while True:
        try:
            status = _status_with_transparent()
            socketio.emit('status_update', status)
            socketio.emit('stats_update', proxy.stats.to_dict())
            socketio.emit('rules_update', proxy.get_rules())
            time.sleep(2)
        except Exception as e:
            print(f"监控错误: {e}")
            time.sleep(5)

# 启动后台监控
monitor_thread = threading.Thread(target=background_monitor, daemon=True)
monitor_thread.start()


# HTTP/SOCKS5 代理回调
def _proxy_callback(host):
    action = proxy.should_proxy(host)
    proxy.record_access(host, action)
    # 透明代理模式下强制走上游，避免 SmartProxy 直连时被 iptables 再次重定向造成回环
    if config.get("transparent_proxy.force_all_via_upstream", False):
        return "proxy"
    return action

def _result_callback(host, success, bytes_down=0, bytes_up=0, duration=0):
    """连接成功/失败时更新规则状态及速度"""
    proxy.record_access_result(host, success, bytes_down, bytes_up, duration)


# 启动 HTTP 和 SOCKS5 代理（自动收集流量）
_http_proxy_thread = None
_socks5_proxy_thread = None

def start_proxies():
    global _http_proxy_thread, _socks5_proxy_thread
    upstream_port = config.get("ssh_tunnel.local_port", 1080)
    
    if config.get("http_proxy.enabled", True) and not (_http_proxy_thread and _http_proxy_thread.is_alive()):
        port = config.get("http_proxy.port", 8080)
        _http_proxy_thread = threading.Thread(
            target=lambda: run_proxy_server(
                "127.0.0.1", port, _proxy_callback,
                socks_host="127.0.0.1", socks_port=upstream_port,
                result_callback=_result_callback,
            ),
            daemon=True,
        )
        _http_proxy_thread.start()
        print(f"📡 HTTP 代理: 127.0.0.1:{port} (监控 HTTP/HTTPS)")
    
    if config.get("socks5_proxy.enabled", True) and not (_socks5_proxy_thread and _socks5_proxy_thread.is_alive()):
        port = config.get("socks5_proxy.port", 1081)
        _socks5_proxy_thread = threading.Thread(
            target=lambda: run_socks5_proxy_server(
                "127.0.0.1", port, _proxy_callback,
                upstream_socks_host="127.0.0.1", upstream_socks_port=upstream_port,
                result_callback=_result_callback,
            ),
            daemon=True,
        )
        _socks5_proxy_thread.start()
        print(f"📡 SOCKS5 代理: 127.0.0.1:{port} (监控 SOCKS5)")


# ============ Web 路由 ============

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')


@app.route('/proxy.pac')
def proxy_pac():
    """
    生成 PAC 文件。所有流量经 SmartProxy（便于记录状态），
    SmartProxy 内部按规则直连或走上游代理，实现「默认直连、该走代理才走」。
    """
    port = config.get("http_proxy.port", 8080)
    # 全部经 SmartProxy，由 SmartProxy 按规则路由；仅 localhost 直连
    js = '''function FindProxyForURL(url, host) {
  if (isPlainHostName(host) || host === "127.0.0.1" || host === "localhost") return "DIRECT";
  return "PROXY 127.0.0.1:''' + str(port) + '''";
}
'''
    return js, 200, {
        "Content-Type": "application/x-ns-proxy-autoconfig",
        "Cache-Control": "no-cache, max-age=60",
    }


@app.route('/transparent-proxy')
def transparent_proxy_help():
    """透明代理说明"""
    path = os.path.join(os.path.dirname(__file__), 'docs', 'TRANSPARENT_PROXY.md')
    if os.path.exists(path):
        with open(path) as f:
            content = f.read().replace('<', '&lt;').replace('\n', '<br>\n')
    else:
        content = "文档未找到"
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>透明代理</title></head><body style="max-width:800px;margin:24px auto;padding:16px;font-family:sans-serif;"><a href="/">← 返回</a><hr><div style="white-space:pre-wrap;">{content}</div></body></html>'


@app.route('/ubuntu24')
def ubuntu24_help():
    """Ubuntu 24 配置指南"""
    path = os.path.join(os.path.dirname(__file__), 'UBUNTU24.md')
    with open(path) as f:
        content = f.read().replace('<', '&lt;').replace('\n', '<br>\n')
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ubuntu 24 配置</title></head><body style="max-width:800px;margin:24px auto;padding:16px;font-family:sans-serif;"><a href="/">← 返回</a><hr><div style="white-space:pre-wrap;">{content}</div></body></html>'


@app.route('/configure')
def configure_help():
    """配置指南"""
    path = os.path.join(os.path.dirname(__file__), 'CONFIGURE.md')
    with open(path) as f:
        content = f.read().replace('<', '&lt;').replace('\n', '<br>\n')
    return f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>配置指南</title></head><body style="max-width:800px;margin:24px auto;padding:16px;font-family:sans-serif;"><a href="/">← 返回</a><hr><div style="white-space:pre-wrap;">{content}</div></body></html>'


# ============ API 路由 ============

@app.route('/api/status')
def api_status():
    """获取系统状态"""
    return jsonify(proxy.get_status())


@app.route('/api/stats')
def api_stats():
    """获取统计信息"""
    return jsonify(proxy.stats.to_dict())


@app.route('/api/rules')
def api_rules():
    """获取规则列表"""
    return jsonify(proxy.get_rules())


@app.route('/api/rules', methods=['POST'])
def api_add_rule():
    """添加规则"""
    data = request.json
    result = proxy.add_rule(
        domain=data.get('domain'),
        action=data.get('action', 'proxy'),
        priority=data.get('priority', 0)
    )
    return jsonify(result)


@app.route('/api/rules/<path:domain>', methods=['DELETE'])
def api_delete_rule(domain):
    """删除规则"""
    result = proxy.remove_rule(domain)
    return jsonify(result)


@app.route('/api/rules/test-all', methods=['POST'])
def api_test_all():
    """测试所有规则"""
    def run_test():
        proxy.test_all_rules()
        socketio.emit('rules_update', proxy.get_rules())
    
    # 在后台运行测试
    threading.Thread(target=run_test, daemon=True).start()
    return jsonify({"message": "开始测试所有规则"})


@app.route('/api/rules/clear-status', methods=['POST'])
def api_clear_status():
    """清除所有状态"""
    proxy.clear_all_status()
    return jsonify({"message": "已清除所有状态"})


@app.route('/api/rules/<path:domain>/test', methods=['POST'])
def api_test_rule(domain):
    """测试单个规则"""
    result = proxy.test_rule_speed(domain)
    return jsonify(result)


@app.route('/api/rules/<path:domain>/toggle', methods=['POST'])
def api_toggle_rule(domain):
    """切换规则状态"""
    result = proxy.toggle_rule(domain)
    return jsonify(result)


@app.route('/api/ssh/status')
def api_ssh_status():
    """SSH 隧道状态"""
    return jsonify({
        'running': proxy.ssh_tunnel_running(),
        'port': config.get('ssh_tunnel.local_port'),
    })


@app.route('/api/ssh/start', methods=['POST'])
def api_ssh_start():
    """启动 SSH 隧道"""
    success = proxy.start_ssh_tunnel()
    return jsonify({
        'success': success,
        'message': None if success else '请检查 config.yaml 中的 remote_host、key 等配置',
    })


@app.route('/api/ssh/stop', methods=['POST'])
def api_ssh_stop():
    """停止 SSH 隧道"""
    proxy.stop_ssh_tunnel()
    return jsonify({'success': True})


def _transparent_proxy_active() -> bool:
    """检测透明代理（redsocks）是否在运行"""
    if os.name != 'posix':
        return False
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "redsocks"],
            capture_output=True, text=True, timeout=2
        )
        return r.returncode == 0 and r.stdout.strip() == "active"
    except Exception:
        return False


def _get_proxy_apps():
    """从 config 读取 proxy_apps，兼容旧格式"""
    apps = config.get("proxy_apps") or []
    if isinstance(apps, list):
        return apps
    return []


def _save_proxy_apps(apps: list):
    """保存 proxy_apps 并确保有 proxy_apps 键"""
    data = config.data
    if "proxy_apps" not in data:
        data["proxy_apps"] = []
    data["proxy_apps"] = apps
    config.save()


@app.route('/api/proxy-apps')
def api_proxy_apps_list():
    """获取走代理的应用列表"""
    return jsonify(_get_proxy_apps())


@app.route('/api/proxy-apps', methods=['POST'])
def api_proxy_apps_add():
    """添加走代理的应用"""
    from smartproxy.proxy_apps import generate_launcher
    data = request.json or {}
    name = (data.get("name") or "").strip()
    exec_cmd = (data.get("exec") or "").strip()
    desktop_name = (data.get("desktop_name") or name).strip()
    if not name or not exec_cmd:
        return jsonify({"success": False, "message": "name 和 exec 必填"}), 400
    name_id = name.lower().replace(" ", "-")
    apps = _get_proxy_apps()
    if any(a.get("name", "").lower().replace(" ", "-") == name_id for a in apps):
        return jsonify({"success": False, "message": f"应用 {name} 已存在"}), 400
    try:
        bin_path, desktop_path = generate_launcher(name_id, exec_cmd, desktop_name)
        apps.append({"name": name_id, "exec": exec_cmd, "desktop_name": desktop_name})
        _save_proxy_apps(apps)
        return jsonify({"success": True, "message": f"已生成 {bin_path}，从应用菜单启动「{desktop_name} (经代理)」"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/api/proxy-apps/<name>', methods=['DELETE'])
def api_proxy_apps_remove(name):
    """移除走代理的应用"""
    from smartproxy.proxy_apps import remove_launcher
    apps = _get_proxy_apps()
    name_id = name.strip().lower().replace(" ", "-")
    found = None
    for i, a in enumerate(apps):
        if (a.get("name") or "").lower().replace(" ", "-") == name_id:
            found = (i, a)
            break
    if not found:
        return jsonify({"success": False, "message": f"未找到应用 {name}"}), 404
    i, a = found
    remove_launcher(name_id, a.get("desktop_name"))
    apps.pop(i)
    _save_proxy_apps(apps)
    return jsonify({"success": True})


# 预设：常见应用的可执行路径检测
PROXY_APP_PRESETS = [
    {"id": "telegram", "name": "telegram", "desktop_name": "Telegram", "detect": None},
    {"id": "discord", "name": "discord", "desktop_name": "Discord", "exec": "discord"},
]


def _detect_telegram() -> str:
    import shutil
    if shutil.which("telegram-desktop"):
        return "telegram-desktop"
    for p in [
        Path("/snap/bin/telegram-desktop"),
        Path.home() / "install/Telegram/Telegram",
        Path.home() / "Telegram/Telegram",
    ]:
        if p.exists() and os.access(p, os.X_OK):
            return str(p)
    try:
        r = subprocess.run(["flatpak", "list", "--app"], capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and "org.telegram.desktop" in (r.stdout or ""):
            return "flatpak run org.telegram.desktop"
    except Exception:
        pass
    return ""


@app.route('/api/proxy-apps/presets')
def api_proxy_apps_presets():
    """获取可添加的预设应用"""
    presets = []
    for p in PROXY_APP_PRESETS:
        if p["id"] == "telegram":
            exec_cmd = _detect_telegram()
            if not exec_cmd:
                exec_cmd = "/path/to/Telegram"
        else:
            exec_cmd = p.get("exec", "")
        presets.append({
            "id": p["id"],
            "name": p["name"],
            "desktop_name": p["desktop_name"],
            "exec": exec_cmd,
        })
    return jsonify(presets)


@app.route('/api/transparent-proxy')
def api_transparent_proxy_status():
    """透明代理状态"""
    return jsonify({
        "enabled": config.get("transparent_proxy.auto_enable", False),
        "active": _transparent_proxy_active(),
        "linux": sys.platform == "linux",
    })


@app.route('/api/transparent-proxy/enable', methods=['POST'])
def api_transparent_proxy_enable():
    """启用透明代理"""
    if sys.platform != "linux":
        return jsonify({"success": False, "message": "仅支持 Linux"}), 400
    config.set("transparent_proxy.auto_enable", True)
    config.set("transparent_proxy.force_all_via_upstream", True)  # 避免连接回环
    script_dir = os.path.dirname(os.path.abspath(__file__))
    setup_script = os.path.join(script_dir, "scripts", "setup-transparent-proxy.sh")
    if os.path.exists(setup_script):
        r = subprocess.run(["sudo", "bash", setup_script, "enable"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return jsonify({"success": True})
        return jsonify({"success": False, "message": r.stderr or r.stdout or "执行失败"}), 500
    return jsonify({"success": False, "message": "setup 脚本未找到"}), 500


@app.route('/api/transparent-proxy/disable', methods=['POST'])
def api_transparent_proxy_disable():
    """禁用透明代理"""
    config.set("transparent_proxy.auto_enable", False)
    config.set("transparent_proxy.force_all_via_upstream", False)
    if sys.platform != "linux":
        return jsonify({"success": True})  # 配置已更新
    script_dir = os.path.dirname(os.path.abspath(__file__))
    setup_script = os.path.join(script_dir, "scripts", "setup-transparent-proxy.sh")
    if os.path.exists(setup_script):
        r = subprocess.run(["sudo", "bash", setup_script, "disable"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return jsonify({"success": True})
        return jsonify({"success": False, "message": r.stderr or r.stdout or "执行失败"}), 500
    return jsonify({"success": True})


@app.route('/api/test/<path:target>')
def api_test_target(target):
    """测试目标域名/IP"""
    result = proxy.test_target(target)
    return jsonify(result)


@app.route('/api/logs')
def api_logs():
    """获取日志"""
    count = request.args.get('count', 100, type=int)
    return jsonify(proxy.get_logs(count))


# ============ WebSocket 事件 ============

def _status_with_transparent():
    """合并透明代理状态到 status"""
    s = proxy.get_status()
    s["transparent_proxy"] = {
        "enabled": config.get("transparent_proxy.auto_enable", True),
        "active": _transparent_proxy_active(),
        "linux": sys.platform == "linux",
    }
    return s


@socketio.on('connect')
def handle_connect():
    """客户端连接"""
    print('客户端已连接')
    socketio.emit('status_update', _status_with_transparent())
    socketio.emit('stats_update', proxy.stats.to_dict())
    socketio.emit('rules_update', proxy.get_rules())


@socketio.on('request_update')
def handle_request_update():
    """客户端请求刷新数据"""
    socketio.emit('status_update', _status_with_transparent())
    socketio.emit('stats_update', proxy.stats.to_dict())
    socketio.emit('rules_update', proxy.get_rules())


@socketio.on('disconnect')
def handle_disconnect():
    """客户端断开"""
    print('客户端已断开')


# ============ 错误处理 ============

@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'Not found'}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'Internal server error'}), 500


# ============ 主程序 ============

if __name__ == '__main__':
    import sys
    # 透明代理自动配置（需 sudo，会提示输入密码）
    if config.get('transparent_proxy.auto_enable', False) and sys.platform == 'linux':
        try:
            from smartproxy.transparent_proxy import ensure_transparent_proxy
            ensure_transparent_proxy()
        except Exception as e:
            print(f"透明代理跳过: {e}")
    
    # 仅当配置了远程主机时自动启动 SSH 隧道
    if config.get('ssh_tunnel.remote_host'):
        proxy.start_ssh_tunnel()
    
    # 启动 HTTP 和 SOCKS5 代理（自动收集流量）
    start_proxies()
    
    # 打印启动信息
    print("\n" + "="*60)
    print("🎯 SmartProxy 已启动")
    print("="*60)
    print(f"\n🌐 Web 界面: http://localhost:5000")
    print(f"📊 API: http://localhost:5000/api/")
    print(f"\n💡 使用说明:")
    print("  1. 打开浏览器访问 http://localhost:5000")
    print("  2. 代理应用: 在网页添加 Telegram 等，从应用菜单启动「xxx (经代理)」，其他应用默认直连")
    print("  3. 系统代理(可选): HTTP → http://127.0.0.1:8080 | SOCKS5 → socks5://127.0.0.1:1081")
    print("  4. 添加/删除/编辑代理规则")
    print("  5. 管理 SSH 隧道")
    print("\n按 Ctrl+C 停止服务")
    print("="*60 + "\n")
    
    # 启动 Flask
    socketio.run(app, 
        host='0.0.0.0', 
        port=5000, 
        debug=False,
        allow_unsafe_werkzeug=True)
