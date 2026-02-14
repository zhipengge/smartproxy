# SmartProxy

智能流量分析工具，按域名规则自动选择直连或代理。**网页可配置**需走代理的应用（如 Telegram），其他应用默认直连，Cursor、浏览器等不受影响。

## 功能特性

- **代理应用**：网页添加 Telegram、Discord 等，点击「启动」或从应用菜单启动「xxx (经代理)」，其他应用默认直连（经 proxychains 走 SSH 隧道 1080）
- **规则管理**：按域名配置代理/直连，支持通配符（`*.example.com`）
- **SSH 隧道**：通过 SSH 建立 SOCKS5 上游代理
- **自动收集**：系统代理设为 SmartProxy 后，自动记录访问并更新状态
- **速度测试**：测试各规则的直连/代理速度
- **实时状态**：WebSocket 推送状态、统计、规则列表

## 环境要求

- Python 3.10+
- pip 或 pipenv
- Linux（推荐）；其他系统可仅用 HTTP/SOCKS5 代理

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 代理应用依赖（Telegram 等走代理必需）
sudo apt install proxychains4

# 3. 首次配置
python setup.py

# 4. 启动
python app.py
```

访问 http://localhost:5000，在「代理应用」中添加 Telegram 等，从应用菜单启动「xxx (经代理)」即可。

**完整步骤见** [docs/INSTALL.md](docs/INSTALL.md)

### 代理应用实现原理

代理应用（如 Telegram）不认系统代理，需通过 **proxychains** 强制走代理：

```
应用启动 → proxychains 包装 → proxychains.conf → socks5://127.0.0.1:1080 (SSH 隧道)
```

- **proxychains**：用 LD_PRELOAD 拦截应用的网络调用，强制经 SOCKS5 发出
- **1080 端口**：SSH 隧道的本机 SOCKS5 出口，直连 VPS
- 不走 SmartProxy 1081，兼容性更好

详见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#代理应用实现原理)

### 配置文件

`~/.config/smartproxy/config.yaml`：

```yaml
ssh_tunnel:
  local_port: 1080
  remote_host: "your-vps-ip"   # 需境外 VPS 才能访问 Telegram 等
  remote_port: 22
  user: root
  key: /path/to/id_rsa         # 可选，null 表示密码登录

proxy_apps: []                 # 网页添加，格式 [{name, exec, desktop_name}]

http_proxy:
  enabled: true
  port: 8080
```

## 项目结构

```
smartproxy/
├── app.py                # Flask 应用入口
├── setup.py              # 配置向导
├── smartproxy/           # 核心模块
│   ├── config.py         # 配置管理
│   ├── core.py           # 规则、SSH、测试
│   ├── proxy_server.py   # HTTP/SOCKS5 代理
│   ├── proxy_apps.py     # 代理应用管理
│   └── transparent_proxy.py
├── scripts/
│   ├── install-transparent-deps.sh   # 透明代理系统依赖（可选）
│   ├── setup-transparent-proxy.sh    # 透明代理启用/禁用
│   └── make-proxy-launcher.sh        # 命令行生成启动脚本（备选）
├── docs/
│   ├── INSTALL.md            # 安装与使用教程
│   ├── ARCHITECTURE.md       # 架构评估
│   └── TRANSPARENT_PROXY.md  # 透明代理说明
└── templates/
    └── index.html
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/proxy-apps | 代理应用列表 |
| POST | /api/proxy-apps | 添加代理应用 |
| POST | /api/proxy-apps/\<name\>/launch | 启动代理应用 |
| DELETE | /api/proxy-apps/\<name\> | 移除代理应用 |
| GET | /api/proxy-apps/presets | 预设应用（含自动检测路径） |
| GET | /api/status | 系统状态 |
| GET | /api/stats | 流量统计 |
| GET | /api/rules | 规则列表 |
| POST | /api/rules | 添加规则 |
| DELETE | /api/rules/\<domain\> | 删除规则 |
| POST | /api/rules/\<domain\>/test | 测试规则 |
| POST | /api/rules/test-all | 测试所有规则 |
| POST | /api/rules/clear-status | 清除状态 |
| GET | /api/ssh/status | SSH 隧道状态 |
| POST | /api/ssh/start | 启动 SSH 隧道 |
| POST | /api/ssh/stop | 停止 SSH 隧道 |
| GET | /api/transparent-proxy | 透明代理状态 |
| POST | /api/transparent-proxy/enable | 启用透明代理 |
| POST | /api/transparent-proxy/disable | 禁用透明代理 |
| GET | /api/test/\<target\> | 测试目标 |
| GET | /api/logs | 日志 |

## 系统代理（可选）

将系统代理设为以下任一端口，可收集流量并按规则路由：

| 类型 | 地址 |
|------|------|
| HTTP/HTTPS | `http://127.0.0.1:8080` |
| SOCKS5 | `socks5://127.0.0.1:1081` |

**注意：** `socks5://127.0.0.1:1080` 是 SSH 隧道直连，不经过 SmartProxy。

## 文档

| 文档 | 说明 |
|------|------|
| [docs/INSTALL.md](docs/INSTALL.md) | 安装与使用完整教程（按此配置环境） |
| [CONFIGURE.md](CONFIGURE.md) | 系统代理配置指南 |
| [docs/TRANSPARENT_PROXY.md](docs/TRANSPARENT_PROXY.md) | 透明代理（高级） |
| [UBUNTU24.md](UBUNTU24.md) | Ubuntu 24 PAC 配置 |

## 故障排除

| 现象 | 解决办法 |
|------|----------|
| 代理应用添加后无法启动 | 安装 `sudo apt install proxychains4` |
| Telegram 仍无法连接 | 检查 VPS 是否为境外，本地执行 `curl -x socks5://127.0.0.1:1080 https://api.telegram.org` 测试 |
| SSH 隧道启动失败 | 检查 config.yaml 中 remote_host、key |
| 总请求为 0 | 将系统代理设为 `http://127.0.0.1:8080` |

## 许可证

MIT
