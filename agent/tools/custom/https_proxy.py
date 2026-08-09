"""
简易 HTTPS 代理 - 解决 WSL 中 TLS 握手超时问题
在 Windows 端运行，WSL 通过此代理访问 HTTPS
"""
import socket
import threading
import select
import sys
import time

from agent.config import weixin_proxy_port as _cfg_proxy_port
PROXY_HOST = "0.0.0.0"
PROXY_PORT = _cfg_proxy_port()

# DNS 缓存
_dns_cache = {}
_dns_lock = threading.Lock()

def _resolve_host(host: str) -> str:
    """解析域名，带缓存"""
    with _dns_lock:
        if host in _dns_cache:
            return _dns_cache[host]
    try:
        ip = socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_STREAM)[0][4][0]
        with _dns_lock:
            _dns_cache[host] = ip
        return ip
    except Exception:
        return host

def handle_client(client_sock):
    """处理 CONNECT 隧道"""
    remote_sock = None
    try:
        client_sock.settimeout(30)
        data = client_sock.recv(4096)
        if not data:
            print(f"[Proxy] Client sent no data, closing", flush=True)
            client_sock.close()
            return

        # 解析 CONNECT 请求: CONNECT host:port HTTP/1.1
        first_line = data.split(b"\r\n")[0].decode(errors="replace")
        print(f"[Proxy] Received: {first_line}", flush=True)
        
        if not first_line.startswith("CONNECT"):
            print(f"[Proxy] Not a CONNECT request, closing", flush=True)
            client_sock.close()
            return

        parts = first_line.split()
        if len(parts) < 2:
            print(f"[Proxy] Invalid CONNECT request", flush=True)
            client_sock.close()
            return

        host, port = parts[1].split(":")
        port = int(port)
        
        # 预解析 DNS
        ip = _resolve_host(host)
        print(f"[Proxy] {host}:{port} -> {ip}:{port}", flush=True)
        
        # 连接目标服务器（带重试）
        for attempt in range(3):
            try:
                remote_sock = socket.create_connection((ip, port), timeout=10)
                print(f"[Proxy] Connected to {host}:{port} (attempt {attempt+1})", flush=True)
                break
            except Exception as e:
                print(f"[Proxy] Connect attempt {attempt+1} failed: {e}", flush=True)
                if attempt < 2:
                    time.sleep(1)
                else:
                    raise
        
        client_sock.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        print(f"[Proxy] Sent 200 to client", flush=True)

        # 双向转发
        sockets = [client_sock, remote_sock]
        while True:
            readable, _, _ = select.select(sockets, [], [], 60)
            if not readable:
                print(f"[Proxy] Select timeout", flush=True)
                break
            for sock in readable:
                try:
                    data = sock.recv(32768)
                except Exception as e:
                    print(f"[Proxy] Recv error: {e}", flush=True)
                    data = None
                if not data:
                    print(f"[Proxy] Connection closed by {'client' if sock is client_sock else 'remote'}", flush=True)
                    sockets.remove(sock)
                    other = remote_sock if sock is client_sock else client_sock
                    if other in sockets:
                        try:
                            other.close()
                        except Exception:
                            pass
                        sockets.remove(other)
                    break
                other = remote_sock if sock is client_sock else client_sock
                try:
                    other.sendall(data)
                except Exception as e:
                    print(f"[Proxy] Send error: {e}", flush=True)
                    break
            if len(sockets) < 2:
                break
    except Exception as e:
        print(f"[Proxy] Error: {e}", flush=True)
    finally:
        try:
            client_sock.close()
        except Exception:
            pass
        if remote_sock:
            try:
                remote_sock.close()
            except Exception:
                pass
        print(f"[Proxy] Client disconnected", flush=True)

def start_proxy():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((PROXY_HOST, PROXY_PORT))
    server.listen(10)
    print(f"[HTTPS Proxy] 代理已启动: {PROXY_HOST}:{PROXY_PORT}", flush=True)
    while True:
        try:
            client, addr = server.accept()
            print(f"[Proxy] New connection from {addr}", flush=True)
            t = threading.Thread(target=handle_client, args=(client,), daemon=True)
            t.start()
        except Exception as e:
            print(f"[Proxy] Accept error: {e}", flush=True)
            break

if __name__ == "__main__":
    start_proxy()