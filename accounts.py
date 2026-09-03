"""账号导入与存储。

支持两种 token 文本格式：
  - access_token（JWT，eyJ...）
  - ws token（user_01XXX::eyJ...，即 WorkosCursorSessionToken）
以及 JSON 文件（号池导出，如 cursor_accounts_*.json，字段名兼容 access_token/accessToken/token/session_token 等）。
按 user id 去重；同一账号有多个字段时保留优先级最高的可用 token（access/ws > session > token > refresh）。
同一个 JSON 对象里既有 access 类字段又有 refresh_token 时，refresh 会与该 access token 关联保存
（条目字段 "refresh"，可为 None），切号时一并写入本机 Cursor，让 Cursor 能自行续期。

账号会持久化到磁盘（LOCALAPPDATA\\SandClaimer\\accounts.json），下次打开自动加载，无需重复导入。
token 属凭据，用 Windows DPAPI 加密后落盘（绑定当前 Windows 用户，文件拷到别处也解不开）；
DPAPI 不可用时回退明文，保证持久化仍然生效。
"""

import base64
import ctypes
import json
import os
import re
import threading
from ctypes import wintypes

from sand_api import parse_token

# ws token（含 :: 或 %3A%3A）优先，其次裸 JWT。
WS_RE = re.compile(r"user_[A-Za-z0-9]+(?:::|%3A%3A)eyJ[A-Za-z0-9_.\-]+")
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}")

# 字段名 -> 优先级：access_token / ws token 才是调 API 能用的；refresh_token 最低，绝不能覆盖 access。
_TOKEN_PRIORITY = {
    "access_token": 5,
    "accesstoken": 5,
    "ws_token": 5,
    "wstoken": 5,
    "workoscursorsessiontoken": 5,
    "session_token": 4,
    "sessiontoken": 4,
    "token": 3,
    "refresh_token": 1,
    "refreshtoken": 1,
}


def _store_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "SandClaimer", "accounts.json")


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data: bytes, protect: bool):
    """Windows DPAPI 加/解密。protect=True 加密，False 解密。失败返回 None。"""
    if os.name != "nt":
        return None
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
        ok = fn(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out))
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


# 优先级 >= 此值的字段视为「可直接调 API 的 access 类 token」，可与同对象内的 refresh 关联。
_ACCESS_MIN_PRIO = 3
_REFRESH_KEYS = ("refresh_token", "refreshtoken")


def _extract_from_obj(obj, out: list) -> None:
    """递归从任意 JSON 结构里抽取 (优先级, token 字符串, 关联的 refresh_token 或 None)。

    同一个 dict 里同时出现 access 类字段（优先级 >= 3）和 refresh_token/refreshToken 时，
    把 refresh 关联到该 access token；refresh 自身仍按最低优先级单独追加一份，
    以便只有 refresh 的账号也能被识别（不会覆盖已有 access）。
    """
    if isinstance(obj, dict):
        refresh = None
        for key, value in obj.items():
            if isinstance(value, str) and key.lower() in _REFRESH_KEYS and value.strip():
                refresh = value.strip()
                break
        for key, value in obj.items():
            prio = _TOKEN_PRIORITY.get(key.lower())
            if isinstance(value, str) and prio is not None:
                linked = refresh if (prio >= _ACCESS_MIN_PRIO and refresh != value) else None
                out.append((prio, value, linked))
            else:
                _extract_from_obj(value, out)
    elif isinstance(obj, list):
        for item in obj:
            _extract_from_obj(item, out)


def tokens_from_text(text: str) -> list:
    """从纯文本抽取 (优先级, token, None)。ws / 裸 JWT 都按最高优先级，纯文本没有 refresh 可关联。"""
    out = [(5, m.group(0), None) for m in WS_RE.finditer(text)]
    out.extend((5, m.group(0), None) for m in JWT_RE.finditer(text))
    return out


def tokens_from_json_text(text: str) -> list:
    out: list = []
    try:
        _extract_from_obj(json.loads(text), out)
    except Exception:
        pass
    return out


def _clean_groups(raw) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in raw or []:
        value = re.sub(r"\s+", " ", str(name or "").strip())[:32]
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _split_store_inner(inner) -> tuple[list, list]:
    """兼容旧版：加密明文曾经直接是账号数组。"""
    if isinstance(inner, list):
        return inner, []
    if not isinstance(inner, dict):
        return [], []
    items = inner.get("items")
    if not isinstance(items, list):
        items = []
    return items, inner.get("groups") or []


def _norm_group(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())[:32]


class AccountStore:
    """账号表，key 为 user id，天然去重；自动持久化到磁盘。"""

    def __init__(self) -> None:
        self._items: dict[str, dict] = {}
        self._groups: list[str] = []
        self._lock = threading.Lock()
        self._load()

    # ---- 持久化 ----

    def _load(self) -> None:
        path = _store_path()
        try:
            with open(path, "rb") as handle:
                envelope = json.loads(handle.read().decode("utf-8"))
        except Exception:
            return
        items = []
        groups = []
        if isinstance(envelope, dict) and envelope.get("enc") == "dpapi":
            blob = base64.b64decode(envelope.get("data", ""))
            dec = _dpapi(blob, protect=False)
            if dec:
                try:
                    inner = json.loads(dec.decode("utf-8"))
                except Exception:
                    inner = []
                items, groups = _split_store_inner(inner)
        elif isinstance(envelope, dict):
            items, groups = _split_store_inner(envelope)
        self._groups = _clean_groups(groups)
        for it in items:
            if not isinstance(it, dict):
                continue
            uid = it.get("id")
            token = it.get("token")
            if not uid or not token:
                continue
            # 旧版文件没有 refresh 字段，按 None 处理。
            refresh = it.get("refresh")
            label = it.get("label") or ""
            email = it.get("email") or ""
            if not email and "@" in str(label):
                email = label
            group = (it.get("group") or "").strip()
            if group and group not in self._groups:
                self._groups.append(group)
            self._items[uid] = {
                "id": uid,
                "label": label,
                "email": email,
                "group": group,
                "token": token,
                "refresh": refresh if isinstance(refresh, str) and refresh else None,
                "_prio": it.get("_prio", 5),
            }

    def _payload_obj(self) -> dict:
        return {"items": list(self._items.values()), "groups": list(self._groups)}

    def _save(self) -> None:
        path = _store_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            payload = json.dumps(self._payload_obj(), ensure_ascii=False).encode("utf-8")
            enc = _dpapi(payload, protect=True)
            if enc is not None:
                envelope = {"v": 2, "enc": "dpapi", "data": base64.b64encode(enc).decode("ascii")}
            else:
                envelope = {"v": 2, "enc": "none", **self._payload_obj()}
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(envelope, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception:
            pass

    # ---- 导入 ----

    def _add_token(self, token: str, priority: int = 5, refresh: str | None = None):
        try:
            user_id, _jwt, claims = parse_token(token)
        except Exception:
            return None
        existing = self._items.get(user_id)
        # 单独导入的 refresh_token（prio<=1）且账号已存在：只把它补到 existing["refresh"]
        # 上（尚无时），绝不动已有的 access token / _prio。
        if existing is not None and priority <= 1:
            if not existing.get("refresh"):
                existing["refresh"] = token.strip()
            return existing
        # 只在「更高或同等优先级」时覆盖，避免 refresh_token 覆盖 access_token。
        if existing is None or priority >= existing.get("_prio", 0):
            kept_label = (existing.get("label") if existing else "") or ""
            if kept_label and kept_label != user_id:
                label = kept_label
            else:
                label = claims.get("email") or user_id
            email = claims.get("email") or (existing.get("email") if existing else "") or ""
            if not email and "@" in str(label):
                email = label
            kept_refresh = refresh or (existing.get("refresh") if existing else None)
            kept_group = (existing.get("group") if existing else "") or ""
            self._items[user_id] = {
                "id": user_id,
                "label": label,
                "email": email or "",
                "group": kept_group,
                "token": token.strip(),
                "refresh": kept_refresh or None,
                "_prio": priority,
            }
        elif refresh and not existing.get("refresh"):
            # 低优先级条目带来的 refresh 也补到已有账号上（不动 access token）。
            existing["refresh"] = refresh
        return self._items[user_id]

    def _ingest(self, pairs: list) -> list:
        """pairs: [(优先级, token[, refresh])]。按 user id 去重，返回本次涉及的唯一账号列表。"""
        touched: dict[str, dict] = {}
        with self._lock:
            for pair in pairs:
                prio, token = pair[0], pair[1]
                refresh = pair[2] if len(pair) > 2 else None
                item = self._add_token(token, prio, refresh)
                if item:
                    touched[item["id"]] = item
            if touched:
                self._save()
        return [self._public(v) for v in touched.values()]

    def add_text(self, text: str) -> list:
        stripped = (text or "").strip()
        # 粘贴的是 JSON 时先按字段名解析（才能用优先级挑 access_token）；否则走正则。
        if stripped[:1] in "{[":
            pairs = tokens_from_json_text(text) or tokens_from_text(text)
        else:
            pairs = tokens_from_text(text) or tokens_from_json_text(text)
        return self._ingest(pairs)

    def add_json_files(self, paths: list) -> list:
        pairs: list = []
        for path in paths:
            try:
                with open(path, "r", encoding="utf-8-sig") as handle:
                    text = handle.read()
            except Exception:
                continue
            pairs.extend(tokens_from_json_text(text) or tokens_from_text(text))
        return self._ingest(pairs)

    # ---- 读取 / 修改 ----

    def _public(self, item: dict) -> dict:
        return {
            "id": item["id"],
            "label": item.get("label") or "",
            "email": item.get("email") or "",
            "group": item.get("group") or "",
            "hasRefresh": bool(item.get("refresh")),
        }

    def set_label(self, account_id: str, label: str) -> None:
        value = (label or "").strip()
        with self._lock:
            item = self._items.get(account_id)
            if item is None:
                return
            if item.get("label") != value:
                item["label"] = value
                self._save()

    def set_email(self, account_id: str, email: str) -> None:
        """回写探测到的邮箱，不覆盖用户自定义标签。"""
        value = (email or "").strip()
        if "@" not in value:
            return
        with self._lock:
            item = self._items.get(account_id)
            if item is None:
                return
            if item.get("email") != value:
                item["email"] = value
                self._save()

    def set_group(self, account_id: str, group: str) -> None:
        value = _norm_group(group)
        with self._lock:
            item = self._items.get(account_id)
            if item is None:
                return
            if value and value not in self._groups:
                self._groups.append(value)
            if item.get("group") != value:
                item["group"] = value
                self._save()

    def list_groups(self) -> list[str]:
        with self._lock:
            extra = [v.get("group") or "" for v in self._items.values()]
            merged = _clean_groups(list(self._groups) + extra)
            if merged != self._groups:
                self._groups = merged
            return list(self._groups)

    def add_group(self, name: str) -> dict:
        value = _norm_group(name)
        if not value:
            return {"ok": False, "error": "分组名不能为空"}
        with self._lock:
            if value not in self._groups:
                self._groups.append(value)
                self._save()
            return {"ok": True, "groups": list(self._groups)}

    def rename_group(self, old: str, new: str) -> dict:
        src = _norm_group(old)
        dst = _norm_group(new)
        if not src:
            return {"ok": False, "error": "原分组不存在"}
        if not dst:
            return {"ok": False, "error": "新名称不能为空"}
        with self._lock:
            if src not in self._groups:
                return {"ok": False, "error": "原分组不存在", "groups": list(self._groups)}
            if dst != src and dst in self._groups:
                return {"ok": False, "error": "已有同名分组", "groups": list(self._groups)}
            self._groups = [dst if g == src else g for g in self._groups]
            for item in self._items.values():
                if item.get("group") == src:
                    item["group"] = dst
            self._save()
            return {"ok": True, "groups": list(self._groups)}

    def remove_group(self, name: str) -> dict:
        value = _norm_group(name)
        with self._lock:
            self._groups = [g for g in self._groups if g != value]
            for item in self._items.values():
                if item.get("group") == value:
                    item["group"] = ""
            self._save()
            return {"ok": True, "groups": list(self._groups)}

    def set_refresh(self, account_id: str, refresh: str | None) -> None:
        """补写账号的 refresh_token（如本机探测读到的 cursorAuth/refreshToken）；有变化才落盘。"""
        value = (refresh or "").strip() or None
        with self._lock:
            item = self._items.get(account_id)
            if item and value and item.get("refresh") != value:
                item["refresh"] = value
                self._save()

    def list(self) -> list:
        # hasRefresh 供前端在切号前提示「该账号没有 refresh_token，登录态到期后需重新导入」。
        return [self._public(v) for v in self._items.values()]

    def get(self, account_id: str):
        return self._items.get(account_id)

    def remove(self, account_id: str) -> None:
        with self._lock:
            if self._items.pop(account_id, None) is not None:
                self._save()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._save()
