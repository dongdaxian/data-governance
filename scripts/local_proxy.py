# -*- coding: utf-8 -*-
"""本地 TCP 转发器：通过 HTTP CONNECT 代理隧道转发到 Milvus。

gRPC 不支持通过 HTTP 代理建立 CONNECT 隧道（已知问题），
本脚本在本地启动一个 TCP 监听端口，通过代理建立 CONNECT 隧道
转发到 Milvus 服务器，gRPC 直连本地端口即可。

用法：
  python local_proxy.py
  然后设置 MILVUS_URI=http://127.0.0.1:19531
"""

import socket
import threading
import sys
import os

PROXY_HOST = "127.0.0.1"
PROXY_PORT = 15732
TARGET_HOST = "c-63ccc27234f055a0.milvus.aliyuncs.com"
TARGET_PORT = 19530
LOCAL_PORT = 19531

connections = []


def forward(src, dst):
    """双向转发数据。"""
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try:
            src.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass


def handle_client(client_sock):
    """处理客户端连接：通过代理建立 CONNECT 隧道并转发。"""
    try:
        proxy_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy_sock.settimeout(15)
        proxy_sock.connect((PROXY_HOST, PROXY_PORT))

        connect_req = (
            f"CONNECT {TARGET_HOST}:{TARGET_PORT} HTTP/1.1\r\n"
            f"Host: {TARGET_HOST}:{TARGET_PORT}\r\n\r\n"
        )
        proxy_sock.sendall(connect_req.encode())

        response = b""
        while b"\r\n\r\n" not in response:
            chunk = proxy_sock.recv(4096)
            if not chunk:
                break
            response += chunk

        if b"200" not in response.split(b"\r\n")[0]:
            print(f"  [!] CONNECT failed: {response[:100]}")
            client_sock.close()
            proxy_sock.close()
            return

        proxy_sock.settimeout(None)
        client_sock.settimeout(None)

        t1 = threading.Thread(target=forward, args=(client_sock, proxy_sock), daemon=True)
        t2 = threading.Thread(target=forward, args=(proxy_sock, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
    except Exception as e:
        print(f"  [!] Error: {e}")
        try:
            client_sock.close()
        except Exception:
            pass


def main():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", LOCAL_PORT))
    server.listen(50)
    print(f"TCP 转发器已启动: 127.0.0.1:{LOCAL_PORT} -> proxy -> {TARGET_HOST}:{TARGET_PORT}")
    print(f"请设置 MILVUS_URI=http://127.0.0.1:{LOCAL_PORT}")
    print(f"按 Ctrl+C 停止")
    print()

    try:
        while True:
            client_sock, addr = server.accept()
            threading.Thread(target=handle_client, args=(client_sock,), daemon=True).start()
    except KeyboardInterrupt:
        print("\n停止中...")
        server.close()


if __name__ == "__main__":
    main()
