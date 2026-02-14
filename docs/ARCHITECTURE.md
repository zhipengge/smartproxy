# SmartProxy 架构评估

## 一、方案概览

SmartProxy 提供**三层代理入口**，统一由规则引擎决定直连或走代理：

```
         ┌────────────────────────────────────────────────────────────────┐
         │                     SmartProxy 规则引擎                         │
         │         (HTTP/SOCKS5/透明: 按域名规则 直连/代理/未知→试直连)      │
         └─────────────────────────────┬──────────────────────────────────┘
                                        │
    ┌───────────────────────────────────┼───────────────────────────────────┐
    │                                   │                                   │
    ▼                                   ▼                                   ▼
┌──────────────┐              ┌──────────────────┐              ┌─────────────────┐
│ HTTP 8080    │              │ SOCKS5 1081      │              │ 透明代理(高级)   │
│ 系统代理/PAC │              │ 系统代理可选     │              │ redsocks+iptables│
└──────┬───────┘              └────────┬─────────┘              └────────┬────────┘
       │                              │                                 │
       └──────────────────────────────┴─────────────────────────────────┘
                                     │
                                     ▼
                            ┌─────────────────┐
                            │ SSH 隧道 1080   │
                            │ 上游 SOCKS5     │
                            └────────┬────────┘
                                     │
┌────────────────────────────────────┼────────────────────────────────────┐
│ 代理应用（推荐，直连 SSH 隧道）      │                                      │
│ proxychains → 127.0.0.1:1080       │  不走 SmartProxy 1081，兼容性更好    │
└────────────────────────────────────┴────────────────────────────────────┘
```

---

## 二、代理应用实现原理

代理应用（如 Telegram、Discord）**不读取系统代理或环境变量**，普通启动会直连，需通过 **proxychains** 在进程内拦截网络调用。

### 代理链路

```
应用启动 → proxychains 包装 → proxychains.conf → socks5://127.0.0.1:1080 (SSH 隧道)
```

### 各环节说明

| 环节 | 说明 |
|------|------|
| **proxychains** | 通过 LD_PRELOAD 劫持 `connect()` 等系统调用，强制进程的 TCP 连接经配置的 SOCKS5 代理发出 |
| **proxychains.conf** | 位于 `~/.config/smartproxy/proxychains.conf`，配置 `socks5 127.0.0.1 1080` |
| **1080 端口** | SSH 隧道的本机 SOCKS5 出口，流量经 VPS 转发至目标 |
| **为何直连 1080** | 不经过 SmartProxy 1081，避免规则引擎和二次转发，Telegram 等应用兼容性更好 |

### 启动脚本示例

`~/.local/bin/telegram-via-proxy` 内容类似：

```bash
exec proxychains4 -f ~/.config/smartproxy/proxychains.conf /path/to/Telegram -many -workdir ...
```

### 依赖

需安装 `proxychains4`：`sudo apt install proxychains4`。未安装则无法生成代理启动脚本，网页添加代理应用会失败。

### 文件位置

| 类型 | 路径 |
|------|------|
| 启动脚本 | `~/.local/bin/{name}-via-proxy` |
| 桌面入口 | `~/.local/share/applications/{name}-via-proxy.desktop` |
| proxychains 配置 | `~/.config/smartproxy/proxychains.conf` |

---

## 三、优雅性评估

### ✅ 做得好的地方

| 方面 | 评价 |
|------|------|
| **职责分离** | Python 依赖与系统依赖分开安装；`install-transparent-deps.sh` 在项目安装时执行，不污染 app 启动流程 |
| **配置可调** | `transparent_proxy.auto_enable` 控制启动行为，Web 界面可实时开关，无需改配置文件 |
| **多种入口** | 浏览器（HTTP/PAC）、应用（SOCKS5/透明）各有入口，用户按需选择 |
| **统一规则** | 三种入口共用同一规则引擎，行为一致 |
| **渐进式采用** | 可只用系统代理，或只用透明代理，或二者结合 |

### ⚠️ 可改进点

| 方面 | 现状 | 建议 |
|------|------|------|
| **Web 调 sudo** | 从网页启用/禁用需执行 `sudo setup-transparent-proxy.sh`，无免密 sudo 会失败 | 文档说明「可选配置 sudoers 免密」，失败时提示手动命令 |
| **默认 auto_enable** | 已改为 false，推荐使用代理应用 | 透明代理为高级选项，默认关闭 |
| **文档分散** | README、CONFIGURE、TRANSPARENT_PROXY、UBUNTU24 各自独立 | 统一为「安装 → 配置 → 使用场景」结构 |

### 结论

**当前方案整体较优雅**，满足：
- 网页与应用的自动代理访问
- 可配置（config + Web 开关）
- 安装与运行职责清晰
- 文档需整合为一条清晰的安装→使用路径

---

## 四、配置项总览

| 配置路径 | 说明 | 默认值 |
|----------|------|--------|
| `proxy_apps` | 网页配置的代理应用列表 | [] |
| `transparent_proxy.auto_enable` | 启动时是否自动启用透明代理 | false |
| `http_proxy.enabled` | 是否启用 HTTP 代理 | true |
| `http_proxy.port` | HTTP 代理端口 | 8080 |
| `socks5_proxy.enabled` | 是否启用 SOCKS5 代理 | true |
| `socks5_proxy.port` | SOCKS5 代理端口 | 1081 |
| `ssh_tunnel.local_port` | 上游 SOCKS5 端口 | 1080 |
