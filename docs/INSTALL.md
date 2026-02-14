# SmartProxy 安装与使用教程

按以下步骤配置环境，实现：**Telegram 等应用走代理，其他应用（Cursor、浏览器等）默认直连**。

---

## 一、安装依赖

### 1.1 进入项目目录

```bash
cd smartproxy   # 或你的项目路径
```

### 1.2 安装 Python 依赖（必需）

```bash
pip install -r requirements.txt
```

使用 pipenv 时：

```bash
pipenv install
pipenv shell
```

### 1.3 安装 proxychains4（代理应用必需）

用于让 Telegram 等应用经代理启动：

```bash
sudo apt install proxychains4
```

> 不安装则无法生成代理启动脚本，添加代理应用会失败。

### 1.4 透明代理依赖（可选）

仅在使用「透明代理」时需要，**默认不使用**：

```bash
sudo scripts/install-transparent-deps.sh
```

---

## 二、首次配置

### 2.1 运行配置向导

```bash
python setup.py
```

按提示填写：
- VPS IP 地址
- SSH 端口（默认 22）
- SSH 用户（默认 root）
- SSH 密钥路径（可选，直接回车则用密码）
- 本地 SOCKS5 端口（默认 1080）

配置保存到 `~/.config/smartproxy/config.yaml`。

### 2.2 手动编辑配置（可选）

直接编辑 `~/.config/smartproxy/config.yaml`：

```yaml
ssh_tunnel:
  local_port: 1080
  remote_host: "your-vps-ip"    # 需境外 VPS 才能访问 Telegram
  remote_port: 22
  user: root
  key: /path/to/id_rsa         # 或 null 表示密码登录
```

> **重要**：若 VPS 在国内，无法访问 Telegram/Google，需使用境外 VPS。

---

## 三、启动服务

```bash
python app.py
```

- 若有 `remote_host`，会自动启动 SSH 隧道
- 打开 http://localhost:5000 进入 Web 界面

---

## 四、配置 Telegram 走代理（推荐）

### 4.1 在网页添加代理应用

1. 打开 http://localhost:5000
2. 确认「SSH 隧道」为「● 运行中」
3. 在「代理应用」卡片：
   - 点击「Telegram」快捷按钮（会自动检测路径）
   - 或手动填写：应用名 `telegram`，可执行路径如 `~/install/Telegram/Telegram`
4. 点击「添加」

### 4.2 启动 Telegram

在网页点击 **「启动」**，或从应用菜单启动 **「Telegram (经代理)」**，不要启动普通的 Telegram。

应用经 **proxychains** 走代理：proxychains 拦截网络调用，强制经 `socks5://127.0.0.1:1080`（SSH 隧道）发出，Telegram 等不认系统代理的应用可正常访问。

### 4.3 添加其他应用

可按同样方式添加 Discord 等：
- 应用名：`discord`
- 可执行路径：`discord`（若已在 PATH）
- 或自定义：应用名、可执行路径

---

## 五、浏览器代理（可选）

若需要浏览器也走代理：

### 方式 A：PAC（推荐，按规则分流）

1. 系统设置 → 网络 → 代理 → 自动
2. URL 填入：`http://127.0.0.1:5000/proxy.pac`

### 方式 B：手动代理

1. 系统设置 → 网络 → 代理 → 手动
2. HTTP/HTTPS 代理：`127.0.0.1`，端口 `8080`

详见 [CONFIGURE.md](../CONFIGURE.md) 或 http://localhost:5000/configure

---

## 六、使用流程速查

```
1. pip install -r requirements.txt
2. sudo apt install proxychains4
3. python setup.py
4. python app.py
5. 浏览器打开 http://localhost:5000
6. 在「代理应用」添加 Telegram
7. 点击「启动」或从应用菜单启动「Telegram (经代理)」
8. Cursor、浏览器等默认直连，无需配置
```

---

## 七、Web 界面功能

| 功能 | 说明 |
|------|------|
| SSH 隧道 | 启动/停止，查看状态 |
| 代理应用 | 添加/移除、网页点击「启动」 |
| 规则管理 | 添加、删除、编辑、测试域名规则 |
| 流量统计 | 总请求、直连/代理数量 |
| 状态列表 | 各域名访问次数、速度等 |
| 透明代理 | 高级选项，默认折叠 |

---

## 八、故障排除

| 现象 | 可能原因 | 解决办法 |
|------|----------|----------|
| 添加代理应用失败 | 未安装 proxychains4 | `sudo apt install proxychains4` |
| Telegram 启动后无法连接 | VPS 在国内或不可达 | 使用境外 VPS，并检查 SSH 隧道是否运行 |
| 快捷按钮路径为空 | Telegram 未在常见位置 | 手动填写可执行路径（如 `~/install/Telegram/Telegram`） |
| SSH 隧道启动失败 | 配置错误 | 检查 remote_host、key、端口 |
| Cursor 等异常 | 启用了透明代理 | 在「透明代理（高级）」中点击「禁用」 |
| **OpenClaw 连不上 TG** | 代理端口冲突 | OpenClaw 的 Telegram 配置用 `socks5://127.0.0.1:1081` 而非 1080 |
