"""
SmartProxy 核心模块
处理规则匹配、流量分析、SSH 隧道管理等
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from smartproxy.config import Config


@dataclass
class ProxyRule:
    """代理规则"""
    domain: str
    action: str  # "proxy" | "direct" | "block"
    priority: int = 0
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    # 状态信息
    status: Optional[int] = None  # 0=无访问, -1=失败, >0=成功
    down_speed: Optional[float] = None  # 下载速度 (MB/s)
    up_speed: Optional[float] = None    # 上传速度 (MB/s)
    last_test: Optional[str] = None     # 最后测试时间
    # 自动收集的访问统计
    last_access: Optional[str] = None   # 最后访问时间
    access_count: int = 0               # 访问次数
    
    def matches(self, target: str) -> bool:
        """检查域名是否匹配"""
        if not self.enabled:
            return False
        
        target = target.lower()
        domain = self.domain.lower()
        
        # 完全匹配
        if domain == target:
            return True
        
        # 通配符 *.example.com
        if domain.startswith("*."):
            suffix = domain[2:]
            return target.endswith(suffix)
        
        # 子域名 .example.com
        if domain.startswith("."):
            suffix = domain[1:]
            return target.endswith(suffix) or target == suffix
        
        return False


@dataclass
class TrafficStats:
    """流量统计"""
    total_requests: int = 0
    proxied_requests: int = 0
    direct_requests: int = 0
    blocked_requests: int = 0
    start_time: float = field(default_factory=time.time)
    
    def to_dict(self) -> dict:
        runtime = time.time() - self.start_time
        return {
            "runtime_seconds": round(runtime, 2),
            "total_requests": self.total_requests,
            "proxied_requests": self.proxied_requests,
            "direct_requests": self.direct_requests,
            "blocked_requests": self.blocked_requests,
            "proxied_percent": round(self.proxied_requests / max(1, self.total_requests) * 100, 1),
            "direct_percent": round(self.direct_requests / max(1, self.total_requests) * 100, 1),
        }


class SmartProxyCore:
    """SmartProxy 核心类"""
    
    def __init__(self, config: Config):
        self.config = config
        self.rules: List[ProxyRule] = []
        self.stats = TrafficStats()
        self.ssh_process = None
        self.logs: List[dict] = []
        
        # 创建工作目录
        self.work_dir = Path.home() / ".config/smartproxy"
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        # 加载规则
        self.load_rules()
    
    # ============ 规则管理 ============
    
    def load_rules(self):
        """从文件加载规则"""
        self.rules = []
        rules_file = self.work_dir / "rules.yaml"
        if rules_file.exists():
            try:
                with open(rules_file) as f:
                    data = yaml.safe_load(f)
                    for item in data or []:
                        # 只传入 ProxyRule 支持的字段，忽略 status 等运行时状态
                        rule_data = {
                            k: v for k, v in item.items()
                            if k in ("domain", "action", "priority", "enabled", "created_at")
                        }
                        if "domain" in rule_data and "action" in rule_data:
                            self.rules.append(ProxyRule(**rule_data))
            except Exception as e:
                self.log(f"加载规则失败: {e}")
        
        # 添加默认规则
        self._add_default_rules()
    
    def _add_default_rules(self):
        """添加默认规则，使用 *.domain 以匹配主站及所有子域名"""
        defaults = [
            ("*.baidu.com", "direct"),
            ("*.taobao.com", "direct"),
            ("*.qq.com", "direct"),
            ("*.weixin.qq.com", "direct"),
            ("*.163.com", "direct"),
            ("*.gitee.com", "direct"),
            ("*.huggingface.co", "proxy"),
            ("*.github.com", "proxy"),
            ("*.githubusercontent.com", "proxy"),
            ("*.openai.com", "proxy"),
            ("*.anthropic.com", "proxy"),
            ("*.telegram.org", "proxy"),
            ("t.me", "proxy"),
        ]
        
        for domain, action in defaults:
            existing_domains = {r.domain.lower() for r in self.rules}
            if domain.lower() not in existing_domains:
                self.rules.append(ProxyRule(domain=domain, action=action, priority=-1))
        
        # 按优先级排序
        self.rules.sort(key=lambda x: x.priority, reverse=True)
    
    def save_rules(self):
        """保存规则到文件"""
        rules_file = self.work_dir / "rules.yaml"
        data = [
            {
                "domain": r.domain,
                "action": r.action,
                "priority": r.priority,
                "enabled": r.enabled,
            }
            for r in self.rules
        ]
        with open(rules_file, "w") as f:
            yaml.dump(data, f)
    
    def get_rules(self) -> List[dict]:
        """获取规则列表，按优先级降序、域名升序排序"""
        rules_data = [
            {
                "domain": r.domain,
                "action": r.action,
                "priority": r.priority,
                "enabled": r.enabled,
                "created_at": r.created_at,
                "status": r.status,
                "down_speed": r.down_speed,
                "up_speed": r.up_speed,
                "last_test": r.last_test,
                "last_access": r.last_access,
                "access_count": r.access_count,
            }
            for r in self.rules
        ]
        rules_data.sort(key=lambda x: (-x["priority"], x["domain"].lower()))
        return rules_data
    
    def add_rule(self, domain: str, action: str = "proxy", priority: int = 0) -> dict:
        """添加规则"""
        # 检查是否已存在
        for i, rule in enumerate(self.rules):
            if rule.domain == domain:
                self.rules[i] = ProxyRule(domain=domain, action=action, priority=priority)
                self.save_rules()
                self.log(f"更新规则: {domain} -> {action}")
                return {"success": True, "message": f"更新规则: {domain} -> {action}"}
        
        # 添加新规则
        rule = ProxyRule(domain=domain, action=action, priority=priority)
        self.rules.append(rule)
        self.rules.sort(key=lambda x: x.priority, reverse=True)
        self.save_rules()
        self.log(f"添加规则: {domain} -> {action}")
        return {"success": True, "message": f"添加规则: {domain} -> {action}"}
    
    def remove_rule(self, domain: str) -> dict:
        """删除规则"""
        original_count = len(self.rules)
        self.rules = [r for r in self.rules if r.domain != domain]
        
        if len(self.rules) < original_count:
            self.save_rules()
            self.log(f"删除规则: {domain}")
            return {"success": True, "message": f"删除规则: {domain}"}
        else:
            return {"success": False, "message": f"规则不存在: {domain}"}
    
    def toggle_rule(self, domain: str) -> dict:
        """切换规则状态"""
        for rule in self.rules:
            if rule.domain == domain:
                rule.enabled = not rule.enabled
                self.save_rules()
                status = "启用" if rule.enabled else "禁用"
                self.log(f"{status}规则: {domain}")
                return {"success": True, "message": f"{status}规则: {domain}"}
        return {"success": False, "message": f"规则不存在: {domain}"}
    
    # ============ 流量分析 ============
    
    def should_proxy(self, target: str) -> str:
        """判断目标应该使用代理还是直连"""
        self.stats.total_requests += 1
        
        target = target.lower().strip()
        
        # 1. 检查规则
        for rule in self.rules:
            if rule.matches(target):
                if rule.action == "proxy":
                    self.stats.proxied_requests += 1
                elif rule.action == "direct":
                    self.stats.direct_requests += 1
                else:
                    self.stats.blocked_requests += 1
                return rule.action
        
        # 2. 检查 IP 是否为国内
        if self._is_china_ip(target):
            self.stats.direct_requests += 1
            return "direct"
        
        # 3. 其他走代理
        self.stats.proxied_requests += 1
        return "proxy"
    
    def record_access(self, host: str, action: str) -> None:
        """
        记录网络访问，自动更新或添加规则。
        当有流量经过代理时调用，需传入 should_proxy 返回的 action。
        """
        host = host.lower().strip()
        if not host or (host.replace(".", "").replace(":", "").isdigit()):  # 跳过纯 IP
            return
        now = datetime.now().isoformat()
        
        # 查找匹配的规则
        for rule in self.rules:
            if rule.matches(host):
                rule.last_access = now
                rule.access_count = (rule.access_count or 0) + 1
                return
        
        # 无匹配规则，自动添加（新发现的域名）
        existing = {r.domain.lower() for r in self.rules}
        if host not in existing:
            self.rules.append(ProxyRule(
                domain=host,
                action=action,
                priority=0,
                last_access=now,
                access_count=1,
            ))
            self.rules.sort(key=lambda x: x.priority, reverse=True)
            self.save_rules()
            self.log(f"自动添加规则: {host} -> {action}")
    
    def record_access_result(
        self,
        host: str,
        success: bool,
        bytes_down: int = 0,
        bytes_up: int = 0,
        duration: float = 0,
    ) -> None:
        """
        记录访问结果，更新 status 及速度（流量转发时估算）。
        """
        host = host.lower().strip()
        if not host:
            return
        status = 1 if success else -1
        now = datetime.now().isoformat()
        down_speed = (bytes_down / 1024 / 1024 / duration) if duration and duration > 0.1 else None
        up_speed = (bytes_up / 1024 / 1024 / duration) if duration and duration > 0.1 else None
        for rule in self.rules:
            if rule.matches(host):
                rule.status = status
                rule.last_test = now
                if down_speed is not None:
                    rule.down_speed = round(down_speed, 2)
                if up_speed is not None:
                    rule.up_speed = round(up_speed, 2)
                return
        for rule in self.rules:
            if rule.domain.lower() == host:
                rule.status = status
                rule.last_test = now
                if down_speed is not None:
                    rule.down_speed = round(down_speed, 2)
                if up_speed is not None:
                    rule.up_speed = round(up_speed, 2)
                return
    
    def _is_china_ip(self, ip: str) -> bool:
        """判断 IP 是否属于国内（简化版）"""
        # 这里应该使用 geoip2 库或其他 IP 数据库
        # 简化处理：检查常见国内 IP
        china_prefixes = [
            "1.2.", "1.4.", "1.8.", "1.24.", "1.32.",
            "101.", "103.", "111.", "112.", "113.",
            "114.", "115.", "116.", "117.", "118.",
            "119.", "120.", "121.", "122.", "123.",
            "124.", "125.", "180.", "182.", "183.",
            "202.", "203.", "210.", "211.", "218.",
            "219.", "220.", "221.", "222.", "223.",
        ]
        
        for prefix in china_prefixes:
            if ip.startswith(prefix):
                return True
        return False
    
    def test_target(self, target: str) -> dict:
        """测试目标域名的路由"""
        action = self.should_proxy(target)
        
        # 尝试解析域名
        resolved_ips = []
        try:
            import socket
            resolved_ips = socket.gethostbyname_ex(target)[2]
        except:
            pass
        
        return {
            "target": target,
            "action": action,
            "resolved_ips": resolved_ips[:3],  # 只返回前 3 个 IP
            "timestamp": datetime.now().isoformat(),
        }
    
    # ============ SSH 隧道管理 ============
    
    def _port_listening(self, host: str, port: int) -> bool:
        """检查端口是否在监听（不依赖 ssh_process）"""
        try:
            r = subprocess.run(["ss", "-tlnp"], capture_output=True, text=True, timeout=2)
            return f"{host}:{port}" in r.stdout or f":{port}" in r.stdout
        except Exception:
            return False
    
    def ssh_tunnel_running(self) -> bool:
        """检查 SSH 隧道是否运行"""
        if not self.ssh_process:
            return False
        
        # 检查进程是否还在运行
        if self.ssh_process.poll() is not None:
            return False
        
        # 检查端口是否在监听
        try:
            import subprocess
            result = subprocess.run(
                ["ss", "-tlnp"],
                capture_output=True,
                text=True
            )
            port = self.config.get("ssh_tunnel.local_port", 1080)
            return f":{port}" in result.stdout
        except:
            return False
    
    def start_ssh_tunnel(self) -> bool:
        """启动 SSH 隧道"""
        if self.ssh_tunnel_running():
            return True
        
        ssh_config = {
            "host": self.config.get("ssh_tunnel.remote_host"),
            "port": self.config.get("ssh_tunnel.remote_port", 22),
            "user": self.config.get("ssh_tunnel.user", "root"),
            "local_port": self.config.get("ssh_tunnel.local_port", 1080),
            "key": self.config.get("ssh_tunnel.key"),
        }
        
        if not ssh_config["host"]:
            self.log("SSH 隧道未配置")
            return False
        
        # 构建 SSH 命令
        cmd = [
            "ssh",
            "-N",  # 不执行远程命令
            "-D", str(ssh_config["local_port"]),  # SOCKS5 代理
            "-o", "ServerAliveInterval=60",
            "-o", "ServerAliveCountMax=3",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            f"{ssh_config['user']}@{ssh_config['host']}",
            "-p", str(ssh_config["port"]),
        ]
        
        # 如果配置了密钥，添加密钥参数
        key = ssh_config.get("key")
        if key and str(key).lower() not in ["null", "none", ""]:
            cmd.insert(2, "-i")
            cmd.insert(3, str(key))
        
        try:
            self.log(f"启动 SSH 隧道: {ssh_config['user']}@{ssh_config['host']}:{ssh_config['port']}")
            self.ssh_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            
            time.sleep(2)
            
            if self.ssh_tunnel_running():
                self.log(f"SSH 隧道已启动，本地端口: {ssh_config['local_port']}")
                return True
            else:
                self.log("SSH 隧道启动失败")
                return False
                
        except Exception as e:
            self.log(f"启动 SSH 隧道失败: {e}")
            return False
    
    def stop_ssh_tunnel(self):
        """停止 SSH 隧道"""
        if self.ssh_process:
            self.ssh_process.terminate()
            try:
                self.ssh_process.wait(timeout=5)
            except:
                self.ssh_process.kill()
            self.ssh_process = None
            self.log("SSH 隧道已停止")
    
    # ============ 日志和状态 ============
    
    def log(self, message: str, level: str = "INFO"):
        """记录日志"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
        }
        self.logs.insert(0, entry)
        self.logs = self.logs[:1000]  # 保留最近 1000 条
        
        # 打印到控制台
        print(f"[{level}] {message}")
    
    def get_logs(self, count: int = 100) -> List[dict]:
        """获取日志"""
        return self.logs[:count]
    
    def get_status(self) -> dict:
        """获取系统状态"""
        ssh_running = self.ssh_tunnel_running()
        local_port = self.config.get("ssh_tunnel.local_port", 1080)
        http_proxy_enabled = self.config.get("http_proxy.enabled", True)
        http_proxy_port = self.config.get("http_proxy.port", 8080)
        socks5_proxy_enabled = self.config.get("socks5_proxy.enabled", True)
        socks5_proxy_port = self.config.get("socks5_proxy.port", 1081)
        return {
            "running": True,
            "ssh_tunnel": {
                "running": ssh_running,
                "local_port": local_port,
                "remote_host": self.config.get("ssh_tunnel.remote_host"),
            },
            "http_proxy": {
                "enabled": http_proxy_enabled,
                "port": http_proxy_port,
                "url": f"http://127.0.0.1:{http_proxy_port}" if http_proxy_enabled else "-",
            },
            "socks5_proxy": {
                "enabled": socks5_proxy_enabled,
                "port": socks5_proxy_port,
                "url": f"socks5://127.0.0.1:{socks5_proxy_port}" if socks5_proxy_enabled else "-",
            },
            "pac_url": "http://127.0.0.1:5000/proxy.pac",
            "proxy_env": f"socks5://127.0.0.1:{local_port}" if ssh_running else "-",
            "rules_count": len(self.rules),
            "active_rules_count": len([r for r in self.rules if r.enabled]),
            "timestamp": datetime.now().isoformat(),
        }
    
    # ============ 速度测试 ============
    
    def test_speed(self, target: str, use_proxy: bool = False) -> dict:
        """测试目标网速（下载和上传）
        
        Args:
            target: 目标域名
            use_proxy: 是否使用代理测试
        """
        import subprocess
        import time
        import os
        
        result = {
            "target": target,
            "status": 0,
            "down_speed": 0,
            "up_speed": 0,
            "error": None,
        }
        
        # 确定代理设置（只有 use_proxy=True 时才使用代理）
        use_proxychains = False
        proxy = None
        port = self.config.get("ssh_tunnel.local_port", 1080)
        tunnel_ok = self.ssh_tunnel_running() or self._port_listening("127.0.0.1", port)
        if use_proxy and tunnel_ok:
            proxy = f"socks5://127.0.0.1:{port}"
            # curl --proxy 在某些环境下超时，改用 proxychains（与代理应用同路径）
            import shutil
            pc_conf = Path.home() / ".config/smartproxy/proxychains.conf"
            if shutil.which("proxychains4") and pc_conf.exists():
                use_proxychains = True
        
        # 构建请求URL
        if not target.startswith("http"):
            url = f"https://{target}"
        else:
            url = target
        
        # 下载测试 - 下载数据测试速度
        try:
            tmp_file = "/tmp/speed_test_" + str(time.time())
            cmd = ["curl", "-4", "-sL", "-o", tmp_file, "-m", "30", url]  # -4 强制 IPv4
            if use_proxychains:
                pc_conf = Path.home() / ".config/smartproxy/proxychains.conf"
                cmd = ["proxychains4", "-f", str(pc_conf), "-q"] + cmd
            elif proxy:
                cmd.insert(1, proxy)
                cmd.insert(1, "--proxy")
            
            start_time = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            download_time = time.time() - start_time
            
            # 获取下载文件大小
            file_size = 0
            if os.path.exists(tmp_file):
                file_size = os.path.getsize(tmp_file)
                os.remove(tmp_file)
            
            if proc.returncode == 0 and file_size > 0:
                if download_time > 0.1:  # 至少 0.1 秒
                    result["down_speed"] = (file_size / 1024 / 1024) / download_time
                else:
                    # 时间太短，使用估计值
                    result["down_speed"] = file_size / 1024 / 1024 / 0.5
                result["status"] = 1
            elif proc.returncode == 0:
                # 下载成功但文件为空
                result["status"] = 1
                result["down_speed"] = 0.5  # 估计值
            else:
                result["status"] = -1
                result["error"] = proc.stderr.strip()[:100] if proc.stderr else "连接失败"
                
        except Exception as e:
            result["status"] = -1
            result["error"] = str(e)[:100]
        
        # 上传测试
        try:
            test_data = "X" * (1024 * 100)  # 100KB 测试数据
            tmp_file = "/tmp/upload_test_" + str(time.time())
            with open(tmp_file, 'w') as f:
                f.write(test_data)
            
            cmd = ["curl", "-4", "-s", "-o", "/dev/null", "-X", "POST", "--data-binary", f"@{tmp_file}", "-w", "%{time_total}", "-m", "30", url]
            if use_proxychains:
                pc_conf = Path.home() / ".config/smartproxy/proxychains.conf"
                cmd = ["proxychains4", "-f", str(pc_conf), "-q"] + cmd
            elif proxy:
                cmd.insert(1, proxy)
                cmd.insert(1, "--proxy")
            
            start_time = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
            upload_time = time.time() - start_time
            
            os.remove(tmp_file)
            
            if proc.returncode == 0 and upload_time > 0 and result["status"] == 1:
                try:
                    time_total = float(proc.stdout.strip())
                    if time_total > 0.1:
                        result["up_speed"] = (len(test_data) / 1024 / 1024) / time_total
                    else:
                        result["up_speed"] = len(test_data) / 1024 / 1024 / 0.5
                except:
                    pass
        except:
            pass
        
        return result
    
    _TEST_HOST_MAP = {
        "*.telegram.org": "api.telegram.org",
        "*.google.com": "www.google.com",
        "*.googleapis.com": "www.googleapis.com",
        "*.github.com": "api.github.com",
        "*.anthropic.com": "api.anthropic.com",
    }
    
    def test_rule_speed(self, domain: str) -> dict:
        """测试指定规则的速度"""
        for rule in self.rules:
            if rule.domain == domain:
                # 通配符域名需映射到具体可测试主机
                test_target = self._TEST_HOST_MAP.get(domain, domain)
                if test_target.startswith("*."):
                    test_target = "api." + test_target[2:]  # *.x.com -> api.x.com
                # 根据规则类型决定是否使用代理
                use_proxy = (rule.action == "proxy")
                
                speed_result = self.test_speed(test_target, use_proxy=use_proxy)
                
                # 更新规则状态
                rule.status = speed_result["status"]
                rule.down_speed = speed_result["down_speed"] if speed_result["status"] > 0 else 0
                rule.up_speed = speed_result["up_speed"] if speed_result["status"] > 0 else 0
                rule.last_test = datetime.now().isoformat()
                
                if speed_result["status"] > 0:
                    self.log(f"测试 {domain}: ↓{rule.down_speed:.2f}M/s ↑{rule.up_speed:.2f}M/s")
                elif speed_result["status"] == -1:
                    self.log(f"测试 {domain}: 失败")
                else:
                    self.log(f"测试 {domain}: 无访问")
                
                self.save_rules()
                return speed_result
        
        return {"error": "规则不存在"}
    
    def test_all_rules(self) -> dict:
        """测试所有规则"""
        results = []
        for rule in self.rules:
            if rule.enabled:
                result = self.test_rule_speed(rule.domain)
                results.append({"domain": rule.domain, **result})
                time.sleep(1)  # 避免请求过快
        
        return {"tested": len(results), "results": results}
    
    def clear_all_status(self):
        """清除所有状态"""
        for rule in self.rules:
            rule.status = None
            rule.down_speed = None
            rule.up_speed = None
            rule.last_test = None
        self.save_rules()
        self.log("已清除所有状态")
