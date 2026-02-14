"""
SmartProxy HTTP 代理服务器
根据规则决定直连或经 SOCKS5 转发，自动收集访问并更新状态列表
"""

import socket
import threading
import struct
import select
import ssl
from typing import Optional, Callable


def _extract_host_port(url: str) -> tuple:
    """从 URL 或 host:port 解析 host 和 port"""
    url = url.strip()
    if "://" in url:
        url = url.split("://", 1)[1]
    if "/" in url:
        url = url.split("/", 1)[0]
    if ":" in url:
        host, port = url.rsplit(":", 1)
        try:
            port = int(port)
        except ValueError:
            port = 80
    else:
        host, port = url, 80
    return host, port


def _connect_direct(host: str, port: int, timeout: float = 30) -> Optional[socket.socket]:
    """直连目标服务器"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.settimeout(300)  # 连接成功后放宽超时
        return sock
    except Exception:
        return None


def _connect_via_socks5(host: str, port: int, socks_host: str, socks_port: int) -> Optional[socket.socket]:
    """经 SOCKS5 代理连接"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect((socks_host, socks_port))
        sock.send(b'\x05\x01\x00')
        resp = sock.recv(2)
        if len(resp) < 2 or resp[0] != 0x05 or resp[1] != 0x00:
            sock.close()
            return None
        try:
            ip = socket.inet_aton(host)
            atype = 0x01
            addr = ip
        except socket.error:
            addr = host.encode('utf-8')
            atype = 0x03
        req = b'\x05\x01\x00' + bytes([atype]) + bytes([len(addr)]) + addr + struct.pack('>H', port)
        sock.send(req)
        resp = sock.recv(10)
        if len(resp) < 2 or resp[1] != 0x00:
            sock.close()
            return None
        return sock
    except Exception:
        return None


def _relay(sock_a: socket.socket, sock_b: socket.socket, timeout: int = 300):
    """
    双向转发，返回 (bytes_from_a, bytes_from_b, duration_sec)。
    sock_a=client, sock_b=remote，故 bytes_from_a=上传量，bytes_from_b=下载量。
    """
    import time as _time
    bytes_a, bytes_b = 0, 0
    start = _time.time()
    try:
        while True:
            r, _, _ = select.select([sock_a, sock_b], [], [], timeout)
            if not r:
                break
            for s in r:
                try:
                    data = s.recv(16384)
                    if not data:
                        return (bytes_a, bytes_b, _time.time() - start)
                    other = sock_b if s is sock_a else sock_a
                    other.sendall(data)
                    if s is sock_a:
                        bytes_a += len(data)
                    else:
                        bytes_b += len(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return (bytes_a, bytes_b, _time.time() - start)
    finally:
        for s in (sock_a, sock_b):
            try:
                s.close()
            except Exception:
                pass
    return (bytes_a, bytes_b, _time.time() - start)


def handle_client(
    client_socket: socket.socket,
    addr: tuple,
    core_callback: Callable,
    socks_host: str,
    socks_port: int,
    result_callback: Callable = None,
):
    """
    处理单个客户端连接。
    core_callback(host, record_access_func) -> "proxy"|"direct"|"block"
    """
    host = ""
    try:
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client_socket.recv(4096)
            if not chunk:
                return
            request += chunk
        
        lines = request.decode('utf-8', errors='ignore').split('\r\n')
        if not lines:
            return
        first = lines[0].split()
        if len(first) < 2:
            return
        
        method, url = first[0], first[1]
        is_connect = method.upper() == "CONNECT"
        
        if is_connect:
            # CONNECT host:443
            host, port = _extract_host_port(url)
            if port == 80:
                port = 443
        else:
            # GET http://host/path 或 GET /path
            if url.startswith("http://") or url.startswith("https://"):
                host, port = _extract_host_port(url)
            else:
                host, port = "", 80
                for line in lines[1:]:
                    if line.lower().startswith("host:"):
                        host = line.split(":", 1)[1].strip().split(":")[0]
                        break
        
        if not host:
            client_socket.close()
            return
        
        # 调用 core：记录访问并获取动作
        try:
            action = core_callback(host)
        except Exception:
            action = "proxy"
        
        if action == "block":
            client_socket.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            client_socket.close()
            return
        
        if action == "proxy":
            # 先尝试直连（3 秒超时），失败再走代理（直连访问不了才走代理）
            remote = _connect_direct(host, port, timeout=3)
            if not remote:
                remote = _connect_via_socks5(host, port, socks_host, socks_port)
        else:
            remote = _connect_direct(host, port)
        
        if not remote:
            if result_callback:
                try:
                    result_callback(host, False, bytes_down=0, bytes_up=0, duration=0)
                except Exception:
                    pass
            client_socket.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            client_socket.close()
            return
        
        if is_connect:
            client_socket.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            bytes_up, bytes_down, duration = _relay(client_socket, remote)
        else:
            remote.sendall(request)
            bytes_up, bytes_down, duration = _relay(client_socket, remote)
        if result_callback:
            try:
                result_callback(host, True, bytes_down=bytes_down, bytes_up=bytes_up, duration=duration)
            except Exception:
                pass
    except Exception:
        if result_callback and host:
            try:
                result_callback(host, False)
            except Exception:
                pass
    finally:
        try:
            client_socket.close()
        except Exception:
            pass


def run_proxy_server(
    bind_host: str,
    bind_port: int,
    core_callback: Callable,
    socks_host: str = "127.0.0.1",
    socks_port: int = 1080,
    result_callback: Callable = None,
):
    """
    启动 HTTP 代理服务器。
    core_callback(host) 应返回 "proxy" | "direct" | "block"
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind_host, bind_port))
    server.listen(32)
    
    while True:
        try:
            client_sock, addr = server.accept()
            t = threading.Thread(
                target=handle_client,
                args=(client_sock, addr, core_callback, socks_host, socks_port),
                kwargs={"result_callback": result_callback},
                daemon=True,
            )
            t.start()
        except OSError:
            break


# ============ SOCKS5 代理（同时监控 SOCKS5 流量） ============

def _parse_socks5_request(client_socket: socket.socket) -> Optional[tuple]:
    """
    解析 SOCKS5 连接请求，返回 (host, port) 或 None。
    会消费并保留客户端已发送的数据用于后续转发。
    """
    try:
        # 认证协商: VER(5) NMETHODS METHODS
        buf = client_socket.recv(256)
        if len(buf) < 2:
            return None
        if buf[0] != 0x05:
            return None
        # 回复无需认证
        client_socket.sendall(b'\x05\x00')
        
        # 请求: VER CMD RSV ATYP DST.ADDR DST.PORT
        need = 4  # VER CMD RSV ATYP
        while len(buf) < need + 1:
            chunk = client_socket.recv(256)
            if not chunk:
                return None
            buf += chunk
        
        ver, cmd, rsv, atyp = buf[1], buf[2], buf[3], buf[4]
        if cmd != 0x01:  # 只支持 CONNECT
            return None
        
        if atyp == 0x01:  # IPv4
            need += 4 + 2
            while len(buf) < need + 1:  # buf[9:11] needs 11 bytes
                chunk = client_socket.recv(256)
                if not chunk:
                    return None
                buf += chunk
            addr = socket.inet_ntoa(buf[5:9])
            port = struct.unpack('>H', buf[9:11])[0]
        elif atyp == 0x03:  # 域名
            dlen = buf[5]
            need += 1 + dlen + 2
            while len(buf) < need:
                chunk = client_socket.recv(256)
                if not chunk:
                    return None
                buf += chunk
            addr = buf[6:6+dlen].decode('utf-8', errors='replace')
            port = struct.unpack('>H', buf[6+dlen:8+dlen])[0]
        elif atyp == 0x04:  # IPv6
            need += 16 + 2
            while len(buf) < need:
                chunk = client_socket.recv(256)
                if not chunk:
                    return None
                buf += chunk
            addr = socket.inet_ntop(socket.AF_INET6, buf[5:21])
            port = struct.unpack('>H', buf[21:23])[0]
        else:
            return None
        
        # 保存剩余数据供后续转发
        if atyp == 0x01:
            used = 11
        elif atyp == 0x03:
            used = 7 + buf[5]  # 5 + 1(len) + dlen + 2(port)
        else:
            used = 23
        return (addr, port, buf[used:] if len(buf) > used else b'')
    except Exception:
        return None


def handle_socks5_client(
    client_socket: socket.socket,
    addr: tuple,
    core_callback: Callable,
    upstream_socks_host: str,
    upstream_socks_port: int,
    result_callback: Callable = None,
):
    """处理 SOCKS5 客户端连接"""
    host = ""
    try:
        parsed = _parse_socks5_request(client_socket)
        if not parsed:
            client_socket.close()
            return
        
        host, port, rest = parsed
        
        try:
            action = core_callback(host)
        except Exception:
            action = "proxy"
        
        if action == "block":
            if result_callback:
                try:
                    result_callback(host, False, 0, 0, 0)
                except Exception:
                    pass
            client_socket.sendall(b'\x05\x02\x00\x01\x00\x00\x00\x00\x00\x00')
            client_socket.close()
            return
        
        if action == "proxy":
            remote = _connect_direct(host, port, timeout=3)
            if not remote:
                remote = _connect_via_socks5(host, port, upstream_socks_host, upstream_socks_port)
        else:
            remote = _connect_direct(host, port)
        
        if not remote:
            if result_callback:
                try:
                    result_callback(host, False, 0, 0, 0)
                except Exception:
                    pass
            client_socket.sendall(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            client_socket.close()
            return
        
        client_socket.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        if rest:
            remote.sendall(rest)
        bytes_up, bytes_down, duration = _relay(client_socket, remote)
        if result_callback:
            try:
                result_callback(host, True, bytes_down, bytes_up, duration)
            except Exception:
                pass
    except Exception:
        if result_callback and host:
            try:
                result_callback(host, False, 0, 0, 0)
            except Exception:
                pass
    finally:
        try:
            client_socket.close()
        except Exception:
            pass


def run_socks5_proxy_server(
    bind_host: str,
    bind_port: int,
    core_callback: Callable,
    upstream_socks_host: str = "127.0.0.1",
    upstream_socks_port: int = 1080,
    result_callback: Callable = None,
):
    """启动 SOCKS5 代理服务器（监控 SOCKS5 流量）"""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((bind_host, bind_port))
    server.listen(32)
    
    while True:
        try:
            client_sock, addr = server.accept()
            t = threading.Thread(
                target=handle_socks5_client,
                args=(client_sock, addr, core_callback, upstream_socks_host, upstream_socks_port),
                kwargs={"result_callback": result_callback},
                daemon=True,
            )
            t.start()
        except OSError:
            break
