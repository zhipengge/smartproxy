#!/usr/bin/env python3
"""SmartProxy 配置向导"""

import os
from pathlib import Path

CONFIG_FILE = Path.home() / ".config/smartproxy/config.yaml"

print("\n" + "="*50)
print("SmartProxy 配置向导")
print("="*50 + "\n")

remote_host = input("VPS IP 地址: ").strip()
remote_port = input("SSH 端口 (默认22): ").strip() or "22"
user = input("SSH 用户 (默认root): ").strip() or "root"
key_path = input("SSH 密钥路径 (可选，直接回车使用密码): ").strip()
local_port = input("本地 SOCKS5 端口 (默认1080): ").strip() or "1080"

config = f"""ssh_tunnel:
  local_port: {local_port}
  remote_host: {remote_host}
  remote_port: {remote_port}
  user: {user}
  key: {key_path if key_path else 'null'}

general:
  log_level: INFO
  auto_start: false
"""

CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
with open(CONFIG_FILE, "w") as f:
    f.write(config)

print(f"\n✅ 配置已保存: {CONFIG_FILE}")
print(f"\n启动服务: python app.py  （在项目目录下执行）")
print("="*50 + "\n")
