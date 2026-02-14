# 透明代理（高级）

让 **所有应用** 自动走 SmartProxy。**默认关闭**，推荐使用「代理应用」按需配置。

> ⚠️ **注意**：启用后**全部流量**经 VPS，包括 Cursor、系统更新等，可能造成网络异常。推荐改用网页「代理应用」：仅指定应用走代理，其他默认直连。

## 前置条件

- **Linux**（redsocks + iptables 仅支持 Linux）
- 已安装系统依赖：`sudo scripts/install-transparent-deps.sh`
- SmartProxy 已启动（`python app.py`）

## 启用方式

### 1. 启动时自动启用

在 `~/.config/smartproxy/config.yaml` 中设置（**默认 false**）：

```yaml
transparent_proxy:
  auto_enable: true
```

启动 `python app.py` 时，若为 true 会执行透明代理配置（首次需 sudo 密码）。

### 2. Web 界面开关

访问 http://localhost:5000，展开「透明代理（高级）」后点击 **启用** 或 **禁用**。

- **启用**：执行 `sudo scripts/setup-transparent-proxy.sh enable`，并更新 config
- **禁用**：执行 `sudo scripts/setup-transparent-proxy.sh disable`，并更新 config

若未配置免密 sudo，网页操作会失败，可改为在终端执行：

```bash
sudo scripts/setup-transparent-proxy.sh enable   # 启用
sudo scripts/setup-transparent-proxy.sh disable  # 禁用
```

### 3. 配置免密 sudo（可选）

若希望从网页直接启用/禁用，可添加 sudoers 规则：

```bash
# 将 /path/to/smartproxy 替换为实际路径
echo 'youruser ALL=(ALL) NOPASSWD: /path/to/smartproxy/scripts/setup-transparent-proxy.sh' | sudo tee /etc/sudoers.d/smartproxy-transparent
sudo chmod 440 /etc/sudoers.d/smartproxy-transparent
```

## 手动撤销

```bash
cd smartproxy/scripts
sudo ./setup-transparent-proxy.sh disable
```

或在 Web 界面点击「禁用」。

## 关闭启动时自动启用

编辑 `~/.config/smartproxy/config.yaml`：

```yaml
transparent_proxy:
  auto_enable: false
```

之后启动 SmartProxy 不会自动配置透明代理，可在 Web 界面手动启用。

## 原理

redsocks + iptables 将本机 TCP 流量重定向到 SmartProxy SOCKS5 代理（127.0.0.1:1081）。

- 需 root/sudo 配置
- 仅 Linux
- 内网、localhost 等已排除，不会被重定向

## 全部流量走上游

启用透明代理时会自动设置 `force_all_via_upstream: true`，即**全部流量**经 SSH 隧道（VPS）转发，而非按规则直连/代理分流。原因：若 SmartProxy 对「直连」域名发起直连，该连接会被 iptables 再次重定向，造成连接回环、网络不可用。

因此使用透明代理时，国内站点（如百度）也会经 VPS 转发，可能略慢，但网络可正常使用。若需要按规则分流，请使用系统代理 + PAC，不用透明代理。
