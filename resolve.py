"""绕过本机对 Cursor 域名的 DNS 劫持。

有些本地网关工具（如 cgw）会把 cursor.com / api2.cursor.sh 的 DNS 指向本机中转 IP，
导致我们的请求被拦截或用错账号。这里用 DoH（DNS over HTTPS，1.1.1.1）解析这两个主机的真实 IP，
仅对它们覆盖 socket.getaddrinfo；TLS 的 SNI 与证书校验仍用原域名，安全不受影响。
"""

import socket

import requests

CURSOR_HOSTS = {"cursor.com", "api2.cursor.sh"}
_orig_getaddrinfo = socket.getaddrinfo
_cache: dict[str, str] = {}


def _doh(host: str) -> str | None:
    try:
        resp = requests.get(
            "https://1.1.1.1/dns-query",
            params={"name": host, "type": "A"},
            headers={"accept": "application/dns-json"},
            timeout=8,
        )
        for answer in resp.json().get("Answer", []):
            if answer.get("type") == 1 and answer.get("data"):
                return str(answer["data"])
    except Exception:
        return None
    return None


def _patched_getaddrinfo(host, *args, **kwargs):
    if host in CURSOR_HOSTS:
        ip = _cache.get(host) or _doh(host)
        if ip:
            _cache[host] = ip
            # 用真实 IP 连接，但上层仍以原域名做 TLS SNI 与证书校验。
            return _orig_getaddrinfo(ip, *args, **kwargs)
    return _orig_getaddrinfo(host, *args, **kwargs)


def install() -> None:
    """安装 DNS 覆盖。1.1.1.1 本身是 IP、不在覆盖名单内，故 DoH 请求不会自我递归。"""
    socket.getaddrinfo = _patched_getaddrinfo
