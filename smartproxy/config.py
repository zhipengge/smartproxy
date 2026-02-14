"""
SmartProxy 配置管理
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class Config:
    """配置管理类"""
    
    def __init__(self, config_file: str = None):
        if config_file is None:
            config_file = Path.home() / ".config/smartproxy/config.yaml"
        
        self.config_file = Path(config_file)
        self.data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        """加载配置"""
        default_config = {
            "ssh_tunnel": {
                "local_port": 1080,
                "remote_host": "",  # VPS IP
                "remote_port": 22,
                "user": "root",
                "key": None,
            },
            "http_proxy": {
                "enabled": True,
                "port": 8080,  # HTTP 代理，监控 HTTP/HTTPS 流量
            },
            "socks5_proxy": {
                "enabled": True,
                "port": 1081,  # SOCKS5 代理，监控 SOCKS5 流量（1080 留给 SSH 隧道）
            },
            "transparent_proxy": {
                "auto_enable": False,  # 默认关闭，改用代理应用列表
                "force_all_via_upstream": False,
            },
            "proxy_apps": [],  # [{name, exec, desktop_name}] 走代理的应用
            "general": {
                "log_level": "INFO",
                "auto_start": False,
            },
        }
        
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    loaded = yaml.safe_load(f)
                    if loaded:
                        return {**default_config, **loaded}
            except Exception as e:
                print(f"加载配置失败: {e}")
        
        # 创建默认配置
        self.save(default_config)
        return default_config
    
    def save(self, data: Dict[str, Any] = None):
        """保存配置"""
        if data is None:
            data = self.data
        
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 键名，支持点号分隔的路径，如 "ssh_tunnel.local_port"
            default: 默认值
        
        Returns:
            配置值或默认值
        """
        keys = key.split(".")
        value = self.data
        
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        
        return value if value is not None else default
    
    def set(self, key: str, value: Any):
        """
        设置配置值
        
        Args:
            key: 键名，支持点号分隔的路径
            value: 值
        """
        keys = key.split(".")
        data = self.data
        
        for i, k in enumerate(keys[:-1]):
            if k not in data:
                data[k] = {}
            data = data[k]
        
        data[keys[-1]] = value
        self.save()
    
    def delete(self, key: str):
        """删除配置"""
        keys = key.split(".")
        data = self.data
        
        for i, k in enumerate(keys[:-1]):
            if k in data:
                data = data[k]
        
        if keys[-1] in data:
            del data[keys[-1]]
            self.save()
    
    def to_dict(self) -> Dict[str, Any]:
        """获取完整配置"""
        return self.data
    
    def __repr__(self) -> str:
        return f"Config({self.config_file})"


# 便捷函数
def get_config(key: str, default: Any = None) -> Any:
    """获取配置"""
    config = Config()
    return config.get(key, default)


def set_config(key: str, value: Any):
    """设置配置"""
    config = Config()
    config.set(key, value)
