"""Cursor API 域名 DNS 修复：绕过 Clash fake-ip / 本地网关劫持。"""

from __future__ import annotations

import json
import re
import socket
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

CURSOR_DNS_HOSTS: Tuple[str, ...] = (
    "api2.cursor.sh",
    "api2geo.cursor.sh",
    "api2direct.cursor.sh",
    "cursor.com",
)

HOSTS_BEGIN = "# SAND_CURSOR_DNS_BEGIN"
HOSTS_END = "# SAND_CURSOR_DNS_END"
HOSTS_LINE_RE = re.compile(
    r"^\s*(?:\d{1,3}\.){3}\d{1,3}\s+("
    + "|".join(re.escape(host) for host in CURSOR_DNS_HOSTS)
    + r")\s*(?:#.*)?$",
    re.MULTILINE,
)
SAND_DNS_FIX_MARKER = "/*SAND_DNS_FIX_V1*/"

DNS_NODE_TARGETS = frozenset(
    {
        "main.js",
        "extensionHostProcess.js",
    }
)

_doh_cache: Dict[str, str] = {}


def _hosts_path() -> Path:
    if sys.platform == "win32":
        return Path(r"C:\Windows\System32\drivers\etc\hosts")
    return Path("/etc/hosts")


def resolve_doh_a(host: str) -> Optional[str]:
    cached = _doh_cache.get(host)
    if cached:
        return cached
    try:
        query = urllib.parse.urlencode({"name": host, "type": "A"})
        req = urllib.request.Request(
            f"https://1.1.1.1/dns-query?{query}",
            headers={"accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        for answer in payload.get("Answer", []):
            if answer.get("type") == 1 and answer.get("data"):
                ip = str(answer["data"])
                _doh_cache[host] = ip
                return ip
    except Exception:
        return None
    return None


def resolve_system_a(host: str) -> Optional[str]:
    try:
        infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if infos:
            return str(infos[0][4][0])
    except OSError:
        return None
    return None


def resolve_cursor_api_ip() -> Optional[str]:
    for host in ("api2direct.cursor.sh", "api2geo.cursor.sh", "api2.cursor.sh"):
        ip = resolve_doh_a(host)
        if ip:
            return ip
    return None


def build_hosts_entries(tool_version: str) -> List[str]:
    ip = resolve_cursor_api_ip()
    if not ip:
        raise RuntimeError("无法通过 DoH 解析 Cursor API 域名，请检查网络后重试")
    lines = [
        HOSTS_BEGIN,
        f"# sand_patch {tool_version}",
    ]
    for host in CURSOR_DNS_HOSTS:
        lines.append(f"{ip} {host}")
    lines.append(HOSTS_END)
    return lines


def _strip_hosts_block(content: str) -> str:
    pattern = re.compile(
        rf"^\s*{re.escape(HOSTS_BEGIN)}.*?^\s*{re.escape(HOSTS_END)}\s*$",
        re.MULTILINE | re.DOTALL,
    )
    cleaned = pattern.sub("", content)
    cleaned = HOSTS_LINE_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip() + "\n"


def hosts_block_installed() -> bool:
    try:
        content = _hosts_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return HOSTS_BEGIN in content and HOSTS_END in content


def install_hosts(tool_version: str) -> None:
    path = _hosts_path()
    content = path.read_text(encoding="utf-8", errors="replace")
    content = _strip_hosts_block(content)
    block = "\n".join(build_hosts_entries(tool_version)) + "\n\n"
    path.write_text(block + content.lstrip("\n"), encoding="utf-8")
    invalidate_dns_cache()


def remove_hosts() -> None:
    path = _hosts_path()
    content = path.read_text(encoding="utf-8", errors="replace")
    path.write_text(_strip_hosts_block(content), encoding="utf-8")
    invalidate_dns_cache()


_diag_cache: Optional[Dict[str, object]] = None


def invalidate_dns_cache() -> None:
    """写 / 删 hosts 后调用，让下一次 diagnose_dns 重新探测。"""
    global _diag_cache
    _diag_cache = None


def diagnose_dns(use_cache: bool = True) -> Dict[str, object]:
    """探测 DNS 劫持。含 DoH 网络请求 + 读 hosts，单次约 0.6s。

    一次安装/卸载里 inspect_status 会被调用多次，故默认走进程内缓存；
    hosts 变更后由 invalidate_dns_cache() 主动失效。
    """
    global _diag_cache
    if use_cache and _diag_cache is not None:
        return dict(_diag_cache)
    system_ip = resolve_system_a("api2.cursor.sh")
    doh_ip = resolve_cursor_api_ip()
    hosts_installed = hosts_block_installed()
    hijacked = False
    if system_ip and doh_ip and system_ip != doh_ip:
        hijacked = True
    if system_ip and system_ip.startswith("198.18."):
        hijacked = True
    if hosts_installed and doh_ip and system_ip == doh_ip:
        hijacked = False
    result: Dict[str, object] = {
        "system_ip": system_ip,
        "doh_ip": doh_ip,
        "hijacked": hijacked,
        "hosts_installed": hosts_installed,
    }
    _diag_cache = result
    return dict(result)


def dns_node_snippet() -> str:
    hosts = ",".join(f'"{host}":1' for host in CURSOR_DNS_HOSTS)
    return (
        SAND_DNS_FIX_MARKER
        + "(function(){try{var g=typeof globalThis!=='undefined'?globalThis:"
        + "(typeof global!=='undefined'?global:this);"
        + "if(!g||g.__sandDnsFix)return;g.__sandDnsFix=1;"
        + f"var H={{{hosts}}},C={{}},dns=require('dns'),ol=dns.lookup;"
        + "function doh(h,cb){if(C[h])return cb(null,C[h]);"
        + "try{require('https').get('https://1.1.1.1/dns-query?name='+encodeURIComponent(h)+'&type=A',"
        + "{headers:{accept:'application/dns-json'},timeout:5e3},function(r){var d='';"
        + "r.on('data',function(x){d+=x});"
        + "r.on('end',function(){try{var j=JSON.parse(d),ip=null;"
        + "(j.Answer||[]).forEach(function(a){if(a.type===1&&!ip)ip=a.data});"
        + "if(ip){C[h]=ip;return cb(null,ip)}}catch(e){}cb(null,null)});"
        + "}).on('error',function(){cb(null,null)});"
        + "}catch(e){cb(null,null)}}"
        + "dns.lookup=function(h,o,cb){if(typeof o==='function'){cb=o;o={}}"
        + "else if(typeof o==='number'){o={family:o}}"
        + "if(H[h])return doh(h,function(e,ip){if(ip)return cb(null,ip,4);return ol.call(dns,h,o,cb)});"
        + "return ol.call(dns,h,o,cb)};"
        + "if(dns.promises&&dns.promises.lookup){dns.promises.lookup=function(h,o){"
        + "return new Promise(function(res,rej){dns.lookup(h,o,function(e,a,f){"
        + "e?rej(e):res(typeof a==='object'?a:{address:a,family:f})})})}}}catch(e){}})();"
    )


_DNS_NODE_SNIPPET_RE = re.compile(
    re.escape(SAND_DNS_FIX_MARKER) + r"\(function\(\)\{[\s\S]*?\}\)\(\);"
)


def apply_dns_node_patch(content: str) -> Tuple[str, int]:
    if SAND_DNS_FIX_MARKER in content:
        return content, 0
    return dns_node_snippet() + content, 1


def remove_dns_node_patch(content: str) -> Tuple[str, int]:
    next_content, count = _DNS_NODE_SNIPPET_RE.subn("", content)
    residual = next_content.count(SAND_DNS_FIX_MARKER)
    if residual:
        next_content = next_content.replace(SAND_DNS_FIX_MARKER, "")
        count += residual
    return next_content, count
