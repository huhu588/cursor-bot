"""Sand 资格领取器：pywebview（Windows 用 Edge WebView2）+ INFINITY 深色仪表盘 Web UI。

- UI 在 web/ 下（HTML/CSS/JS，哑光紫底 + 纯黑卡片）。
- Python 提供导入/领取能力，通过 window.pywebview.api 暴露给前端。
- 批量领取由前端逐个调用 claim_one 驱动，实时更新每行状态。
"""

import json
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

import webview

import browser_login
import elevate
import local_cursor
import resolve
import sand_patch
from account_usage import fetch_account_usage
from accounts import AccountStore
from dns_fix import diagnose_dns, install_hosts, remove_hosts
from sand_api import claim as claim_token
from sand_api import fetch_general_usage
from sand_api import get_status
from sand_api import parse_token
from account_usage import fetch_period_usage_json

_PATCH_WORKER_FLAG = "--patch-worker"
_RESULT_FLAG = "--result"


_STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "SandClaimer")


def _local_user_id() -> str | None:
    return local_cursor.local_user_id()


def _annotate_accounts(items: list, active_id: str | None = None) -> list:
    """给账号列表打 active 标记。active_id 传入时直接采用（切号成功后 Cursor 刚启动，
    此时读 state.vscdb 可能失败而漏标），否则实时读本机登录态。"""
    active = active_id if active_id else _local_user_id()
    out = []
    for item in items or []:
        row = dict(item)
        row["active"] = bool(active and row.get("id") == active)
        out.append(row)
    return out


def _read_json(name: str, default):
    try:
        with open(os.path.join(_STATE_DIR, name), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _write_json(name: str, data) -> None:
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        path = os.path.join(_STATE_DIR, name)
        with open(path + ".tmp", "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False)
        os.replace(path + ".tmp", path)
    except Exception:
        pass


def resource_path(rel: str) -> str:
    """兼容 PyInstaller onefile：优先用解包目录 _MEIPASS。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


_ANSI_TONE = {
    sand_patch.ANSI_GREEN: "ok",
    sand_patch.ANSI_YELLOW: "warn",
    sand_patch.ANSI_RED: "bad",
}


def _banner_lines() -> list[dict]:
    """把 sand_patch.collect_status_lines() 的 (文本, ANSI 颜色) 转成前端可渲染的 {text, tone}。"""
    return [
        {"text": text, "tone": _ANSI_TONE.get(code, "info")}
        for text, code in sand_patch.collect_status_lines()
    ]


def _build_patch_status(layout: sand_patch.CursorLayout, st: sand_patch.PatchStatus) -> dict:
    dns = diagnose_dns()
    return {
        "ok": True,
        "toolVersion": sand_patch.TOOL_VERSION,
        "version": layout.version,
        "path": str(layout.install_root),
        "installed": bool(st.installed),
        "streamOk": bool(st.stream_mode_installed),
        "verdict": sand_patch.status_verdict(st),
        "ideLeft": st.ide_matches,
        "files": len(st.patched_files),
        "sandRpc": st.sand_rpc_markers,
        "ctxWindow": st.ctx_window_markers,
        "localAgent": st.local_agent_markers,
        "featureFlags": st.feature_flag_markers,
        "admin": elevate.is_admin(),
        "needsElevation": elevate.needs_elevation_for_patch(),
        "client": st.client_markers + st.legacy_client_markers,
        "eligibility": st.eligibility_markers + st.legacy_eligibility_markers,
        "stream": {
            "direct": st.direct_stream_markers,
            "identity": st.agent_host_identity_markers,
            "enable": st.agent_host_enablement_markers,
            "route": st.managed_local_route_markers,
            "runtime": st.local_runtime_load_markers,
            "moveExec": st.move_exec_markers,
            "execBridge": st.exec_bridge_markers,
            "modelRoute": st.model_route_markers,
            "localModel": st.local_model_markers,
        },
        "dns": {
            "hijacked": bool(dns.get("hijacked")),
            "hostsInstalled": bool(dns.get("hosts_installed")),
            "systemIp": dns.get("system_ip"),
            "dohIp": dns.get("doh_ip"),
            "nodeMarkers": st.dns_node_markers,
            "ready": bool(st.dns_ready),
        },
        "externalMarkers": st.external_marker_count,
    }


def _run_patch_worker_action(action: str) -> None:
    if action == "install":
        layout = sand_patch.resolve_cursor_layout()
        sand_patch.install(layout)
        return
    if action == "uninstall":
        layout = sand_patch.resolve_cursor_layout()
        sand_patch.uninstall(layout)
        return
    if action == "dns_install":
        install_hosts(sand_patch.TOOL_VERSION)
        return
    if action == "dns_remove":
        remove_hosts()
        return
    raise sand_patch.SandToolError(f"未知补丁任务：{action}")


def run_patch_worker(action: str, result_path: Path) -> int:
    payload: dict
    try:
        _run_patch_worker_action(action)
        payload = {"ok": True}
    except sand_patch.SandToolError as exc:
        payload = {"ok": False, "error": str(exc)}
    except PermissionError as exc:
        payload = {"ok": False, "error": f"没有写入权限：{exc}"}
    except Exception as exc:
        payload = {"ok": False, "error": str(exc)}
    # 补丁本身已完成/失败，结果文件写不出（目录 ACL、磁盘满）不能再抛异常，
    # 否则父进程只看到「异常退出」而不知道补丁其实成功了；退出码仍反映补丁结果。
    try:
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return 0 if payload.get("ok") else 1


def _parse_patch_worker_argv(argv: list[str]) -> tuple[str, Path] | None:
    if len(argv) < 4 or argv[1] != _PATCH_WORKER_FLAG:
        return None
    action = argv[2]
    if _RESULT_FLAG not in argv:
        return None
    idx = argv.index(_RESULT_FLAG)
    if idx + 1 >= len(argv):
        return None
    return action, Path(argv[idx + 1])


class Api:
    # 属性必须以下划线开头：pywebview 生成 JS 桥接时会递归遍历 js_api 的公开属性
    # （webview/util.py get_functions），遍历到 Window 对象会与建窗线程互等而死锁。
    def __init__(self) -> None:
        self._store = AccountStore()
        self._window: webview.Window | None = None

    def import_files(self) -> dict:
        """弹原生文件选择框，导入 JSON/文本账号文件。"""
        paths = None
        try:
            if self._window is not None:
                paths = self._window.create_file_dialog(
                    webview.OPEN_DIALOG,
                    allow_multiple=True,
                    file_types=("JSON 文件 (*.json)", "文本文件 (*.txt)", "所有文件 (*.*)"),
                )
        except Exception:
            paths = None
        if not paths:
            return {"added": 0, "accounts": _annotate_accounts(self._store.list())}
        added = self._store.add_json_files(list(paths))
        return {"added": len(added), "accounts": _annotate_accounts(self._store.list())}

    def import_text(self, text: str) -> dict:
        added = self._store.add_text(text or "")
        return {"added": len(added), "accounts": _annotate_accounts(self._store.list())}

    def detect_local_account(self) -> dict:
        """以本机账号探测：读本机 Cursor 登录 token，自动加入列表（回写真实邮箱）。"""
        acct = local_cursor.read_local_account()
        if not acct or not acct.get("token"):
            return {"ok": False, "error": "未检测到本机 Cursor 登录（请先在本机 Cursor 登录账号）"}
        touched = self._store.add_text(acct["token"])
        account_id = touched[0]["id"] if touched else None
        email = acct.get("email")
        if account_id and email and "@" in email:
            self._store.set_email(account_id, email)
        # 本机库里若有 refreshToken 一并收下，切回该账号时 Cursor 才能自行续期。
        if account_id and acct.get("refresh"):
            self._store.set_refresh(account_id, acct["refresh"])
        return {
            "ok": True,
            "id": account_id,
            "email": email,
            "membership": acct.get("membership"),
            "accounts": _annotate_accounts(self._store.list()),
        }

    def list_accounts(self) -> list:
        return _annotate_accounts(self._store.list())

    def remove_account(self, account_id: str) -> list:
        self._store.remove(account_id)
        return _annotate_accounts(self._store.list())

    def set_label(self, account_id: str, label: str) -> dict:
        """用户自定义账号名称；空字符串表示清除，列表回退显示邮箱/id。"""
        self._store.set_label(account_id, label)
        return {"ok": True, "accounts": _annotate_accounts(self._store.list())}

    def set_email(self, account_id: str, email: str) -> bool:
        self._store.set_email(account_id, email)
        return True

    def set_group(self, account_id: str, group: str) -> dict:
        self._store.set_group(account_id, group or "")
        return {
            "ok": True,
            "accounts": _annotate_accounts(self._store.list()),
            "groups": self._store.list_groups(),
        }

    def list_groups(self) -> list:
        return self._store.list_groups()

    def add_group(self, name: str) -> dict:
        res = self._store.add_group(name)
        res["accounts"] = _annotate_accounts(self._store.list())
        return res

    # 形参名不能用 JS 保留字：pywebview 以 new Function(params, body) 生成桥接，
    # 出现 new/class/delete 等会抛 SyntaxError，导致 _createApi 中断，
    # 该方法之后（按 dir() 字母序）的所有 API 都不会注册。
    def rename_group(self, old: str, new_name: str) -> dict:
        res = self._store.rename_group(old, new_name)
        res["accounts"] = _annotate_accounts(self._store.list())
        return res

    def remove_group(self, name: str) -> dict:
        res = self._store.remove_group(name)
        res["accounts"] = _annotate_accounts(self._store.list())
        return res

    def clear_accounts(self) -> list:
        self._store.clear()
        return _annotate_accounts(self._store.list())

    def claim_one(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"outcome": "failed", "detail": "账号不存在"}
        try:
            return claim_token(item["token"])
        except Exception as exc:
            return {"outcome": "failed", "detail": str(exc)}

    def status_one(self, account_id: str) -> dict:
        item = self._store.get(account_id)
        if not item:
            return {"error": "账号不存在"}
        try:
            return get_status(item["token"])
        except Exception as exc:
            return {"error": str(exc)}

    def open_login(self, account_id: str) -> dict:
        """用该账号 token 打开一个已登录浏览器并跳到 Sand 领取页，供手动完成（免费号绑卡等）。"""
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        try:
            user_id, jwt, _claims = parse_token(item["token"])
        except Exception as exc:
            return {"ok": False, "error": f"token 解析失败：{exc}"}
        try:
            name = browser_login.open_with_token(user_id, jwt)
            return {"ok": True, "browser": name}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def switch_account(self, account_id: str, reset_machine_id: bool = False) -> dict:
        """一键切号：关闭本机 Cursor → 写入所选账号登录态（可选重置机器码）→ 重开 Cursor。"""
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        try:
            user_id, jwt, claims = parse_token(item["token"])
        except Exception as exc:
            return {"ok": False, "error": f"token 解析失败：{exc}"}
        label = item.get("label") or ""
        email = item.get("email") or (label if "@" in label else "") or (claims.get("email") or user_id)
        membership = None
        try:
            general = fetch_general_usage(user_id, jwt)
            if general:
                membership = general.get("membership")
        except Exception:
            membership = None
        try:
            layout = sand_patch.resolve_cursor_layout()
        except sand_patch.SandToolError as exc:
            return {"ok": False, "error": f"未找到本机 Cursor：{exc}"}
        exe_name = os.path.basename(str(layout.executable)) or "Cursor.exe"
        try:
            sand_patch.close_cursor(layout)
        except sand_patch.SandToolError as exc:
            return {"ok": False, "error": f"关闭 Cursor 失败：{exc}"}
        except Exception as exc:
            return {"ok": False, "error": f"关闭 Cursor 失败：{exc}"}
        # close_cursor 返回后再用 tasklist 轮询确认进程真的退出，否则 state.vscdb 仍被占用，
        # 写进去也会被 Cursor 退出时用内存里的旧登录态覆盖。仍在运行 → 不写库直接返回。
        exited = local_cursor.wait_cursor_exited(exe_name, timeout=8.0, interval=0.25)
        if exited is None:
            # tasklist 不可用，无法确认是否退出：宁可放弃写入也不冒被覆盖/写坏库的风险。
            # 进程本来就在（close 未必生效），不需要 restart。
            return {"ok": False, "error": "无法确认 Cursor 是否已退出（tasklist 不可用），已放弃写入"}
        if exited is False:
            # 超时后再探测一次：进程可能刚好在最后一刻退出；仍在运行才报错（无需 restart，进程本来就在）。
            if local_cursor.cursor_process_running(exe_name) is not False:
                return {"ok": False, "error": "未能关闭 Cursor，请手动完全退出后重试"}

        refresh_token = item.get("refresh") or None
        machine_id_file_written = None

        def restart_after_failure() -> bool:
            """写库/重置机器码失败时把 Cursor 拉回来，避免用户面对一个被关掉的 Cursor。"""
            try:
                return bool(sand_patch.start_cursor(layout))
            except Exception:
                return False

        def failure(message: str) -> dict:
            restarted = restart_after_failure()
            suffix = "（已重新启动 Cursor）" if restarted else "（且未能自动启动 Cursor，请手动打开）"
            return {"ok": False, "error": message + suffix, "cursorRestarted": restarted}

        try:
            local_cursor.write_local_account(
                jwt, email, refresh_token=refresh_token, membership=membership
            )
        except PermissionError as exc:
            return failure(f"state.vscdb 被占用或无写入权限，请确认 Cursor 已完全退出后重试：{exc}")
        except Exception as exc:
            return failure(f"写入登录态失败：{exc}")

        if reset_machine_id:
            try:
                reset_info = local_cursor.reset_machine_ids()
                machine_id_file_written = bool(reset_info.get("machineIdFileWritten"))
            except PermissionError as exc:
                result = failure(f"state.vscdb 被占用或无写入权限，请确认 Cursor 已完全退出后重试：{exc}")
                result["written"] = True
                return result
            except Exception as exc:
                result = failure(f"登录态已写入，但重置机器码失败：{exc}")
                result["written"] = True
                return result

        try:
            started = bool(sand_patch.start_cursor(layout))
        except Exception:
            started = False
        if not started:
            return {
                "ok": False,
                "written": True,
                "error": "登录态已写入，但 Cursor 未能自动启动，请手动打开 Cursor",
            }
        return {
            "ok": True,
            "email": email,
            "id": user_id,
            "resetMachineId": bool(reset_machine_id),
            "hasRefresh": bool(refresh_token),
            "machineIdFileWritten": machine_id_file_written,
            "started": True,
            # 刚写完库就启动 Cursor，此刻读库可能失败；直接用已写入的 user_id 标记 active。
            "accounts": _annotate_accounts(self._store.list(), active_id=user_id),
        }

    def account_detail(self, account_id: str) -> dict:
        """账号详情：Sand 状态 + 账期 API/Auto 额度 + 按模型花费。"""
        item = self._store.get(account_id)
        if not item:
            return {"ok": False, "error": "账号不存在"}
        token = item["token"]
        try:
            user_id, jwt, claims = parse_token(token)
        except Exception as exc:
            return {"ok": False, "error": f"token 解析失败：{exc}"}
        # 账期 JSON 只请求一次，同时喂给 get_status 与 fetch_account_usage，避免重复打接口。
        # 预取失败传空 dict（而不是 None），两者都不会再各自重试一遍。
        try:
            period = fetch_period_usage_json(user_id, jwt) or {}
        except Exception:
            period = {}
        try:
            status = get_status(token, period=period)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        usage = {}
        try:
            usage = fetch_account_usage(token, period=period)
        except Exception as exc:
            usage = {"error": str(exc)}
        preview = jwt[:18] + "…" + jwt[-8:] if len(jwt) > 28 else jwt
        email = status.get("email") or item.get("email") or item.get("label") or user_id
        membership = usage.get("membership") or status.get("membership")
        return {
            "ok": True,
            "id": user_id,
            "email": email,
            "label": item.get("label") or "",
            "group": item.get("group") or "",
            "active": user_id == _local_user_id(),
            "tokenPreview": preview,
            "tokenExpiresAt": usage.get("tokenExpiresAt"),
            "tokenExpired": bool(usage.get("tokenExpired")),
            "status": status,
            "usage": usage,
            "membership": membership,
        }

    # ---- 状态记忆 / 设置持久化 ----

    def load_status(self) -> dict:
        """读取上次每个账号的 Sand 状态（套餐/额度/是否开通），重开时还原到列表。"""
        data = _read_json("status.json", {})
        return data if isinstance(data, dict) else {}

    def save_status(self, data: dict) -> bool:
        _write_json("status.json", data or {})
        return True

    def get_settings(self) -> dict:
        data = _read_json("settings.json", {})
        return data if isinstance(data, dict) else {}

    def set_settings(self, data: dict) -> bool:
        _write_json("settings.json", data or {})
        return True

    # ---- 本机 Cursor Sand 补丁（复用 sand_patch，即原安装工具的成熟逻辑）----

    def set_cursor_path(self, path: str) -> dict:
        """设置自定义 Cursor 路径（传空或 auto 恢复自动检测），随后返回最新补丁状态。"""
        value = (path or "").strip() or "auto"
        try:
            sand_patch.save_cursor_path(value)
        except sand_patch.SandToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return self.patch_status()

    def patch_status(self) -> dict:
        try:
            layout = sand_patch.resolve_cursor_layout()
        except sand_patch.SandToolError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "admin": elevate.is_admin(),
                "needsElevation": elevate.needs_elevation_for_patch(),
            }
        try:
            st = sand_patch.inspect_status(layout)
            return _build_patch_status(layout, st)
        except sand_patch.SandToolError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "version": layout.version,
                "path": str(layout.install_root),
                "admin": elevate.is_admin(),
                "needsElevation": elevate.needs_elevation_for_patch(),
            }

    def patch_report(self) -> dict:
        """只读状态报告：text 前半段与 patch_status.bat 输出逐行相同，后接引擎状态行（print_banner）。"""
        try:
            layout = sand_patch.resolve_cursor_layout()
            st = sand_patch.inspect_status(layout)
            # inspect_status 内部已探测过 DNS，这里命中缓存，不再重复联网。
            dns = diagnose_dns()
        except sand_patch.SandToolError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        rows = [[key, str(value)] for key, value in sand_patch.status_report_rows(layout, st, dns)]
        verdict = sand_patch.status_verdict(st)
        lines = _banner_lines()
        # external_markers 是 GUI 多加的一行，bat 里没有；复制文本前半段要与 bat 逐行一致，
        # 所以这里剔除它（banner 段在有外部标记时本来就会提示）。
        text_parts = [f"{key}: {value}" for key, value in rows if key != "external_markers"]
        text_parts.append(f"status: {verdict}")
        text_parts.append("")
        text_parts.append("---- 引擎状态（等价 sand_patch.py 的 print_banner） ----")
        text_parts.extend(item["text"] for item in lines)
        return {
            "ok": True,
            "verdict": verdict,
            "rows": rows,
            "lines": lines,
            "text": "\n".join(text_parts),
        }

    def _privileged_patch(self, action: str) -> dict:
        if elevate.needs_elevation_for_patch():
            return elevate.run_elevated_patch_worker(action)
        try:
            _run_patch_worker_action(action)
            return {"ok": True}
        except sand_patch.SandToolError as exc:
            return {"ok": False, "error": str(exc)}
        except PermissionError as exc:
            if sys.platform == "win32":
                return elevate.run_elevated_patch_worker(action)
            return {"ok": False, "error": f"没有写入权限，请用管理员身份运行本工具：{exc}"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    _PATCH_FAIL_HINT = (
        "请先完全退出 Cursor；若路径不对，先在上方「设置路径」填写 Cursor 安装目录后重试"
        "（等价 python sand_patch.py set-path）。"
    )

    def _patch_with_banner(self, action: str) -> dict:
        """install/uninstall 之后附带脚本 print_banner() 等价的状态行与判定；失败时附带提示。"""
        res = self._privileged_patch(action)
        if not isinstance(res, dict):
            res = {"ok": False, "error": "补丁任务返回格式无效"}
        if res.get("ok"):
            try:
                res["lines"] = _banner_lines()
                st = sand_patch.inspect_status(sand_patch.resolve_cursor_layout())
                res["verdict"] = sand_patch.status_verdict(st)
            except Exception as exc:
                res.setdefault("lines", [])
                res["verdict"] = "INCOMPLETE"
                res["lines"].append({"text": f"状态复检失败：{exc}", "tone": "warn"})
        else:
            res.setdefault("hint", self._PATCH_FAIL_HINT)
        return res

    def apply_patch(self) -> dict:
        return self._patch_with_banner("install")

    def restore_patch(self) -> dict:
        return self._patch_with_banner("uninstall")

    def apply_dns_fix(self) -> dict:
        """仅写入系统 hosts（DoH IP）；完整打补丁时会一并安装。"""
        return self._privileged_patch("dns_install")

    def remove_dns_fix(self) -> dict:
        return self._privileged_patch("dns_remove")

    _ALLOWED_EXTERNAL_HOSTS = frozenset(
        {
            "infinity-site.cc-infinity.shop",
            "docs.qq.com",
        }
    )

    def open_external_url(self, url: str) -> dict:
        """用系统默认浏览器打开白名单内的官方链接（不在 webview 内跳转）。"""
        raw = (url or "").strip()
        try:
            parsed = urlparse(raw)
        except Exception:
            return {"ok": False, "error": "链接无效"}
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "只允许 http/https 链接"}
        host = (parsed.hostname or "").lower()
        if host not in self._ALLOWED_EXTERNAL_HOSTS:
            return {"ok": False, "error": "不允许打开该域名"}
        try:
            webbrowser.open(raw)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True}


def _apply_native_icon() -> None:
    """开发态用 icon.ico 替换 python.exe 图标；打包后 Nuitka 已把同一 ico 写进 exe。"""
    if sys.platform != "win32":
        return
    ico = resource_path("icon.ico")
    if not os.path.isfile(ico):
        ico = resource_path(os.path.join("web", "favicon.ico"))
    if not os.path.isfile(ico):
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.FindWindowW(None, "Infinity")
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        image_icon = 1
        load_from_file = 0x0010
        wm_seticon = 0x0080
        small = user32.LoadImageW(None, ico, image_icon, 16, 16, load_from_file)
        big = user32.LoadImageW(None, ico, image_icon, 32, 32, load_from_file)
        if small:
            user32.SendMessageW(hwnd, wm_seticon, 0, small)
        if big:
            user32.SendMessageW(hwnd, wm_seticon, 1, big)
    except Exception:
        pass


_JS_RESERVED_WORDS = frozenset(
    """arguments await break case catch class const continue debugger default delete do
    else enum eval export extends false finally for function if implements import in
    instanceof interface let new null package private protected public return static
    super switch this throw true try typeof var void while with yield""".split()
)


def _assert_api_js_safe(api: "Api") -> None:
    """形参名撞 JS 保留字会让 pywebview 的 _createApi 中途抛错，
    使该方法之后的所有 API 静默消失（历史上 rename_group 的 new 就这样干掉了 restore_patch）。"""
    import inspect

    offenders = []
    for name in dir(api):
        if name.startswith("_"):
            continue
        attr = getattr(api, name)
        if not inspect.ismethod(attr):
            continue
        for param in inspect.getfullargspec(attr).args[1:]:
            if param in _JS_RESERVED_WORDS:
                offenders.append(f"{name}({param})")
    if offenders:
        raise RuntimeError(
            "以下 API 形参名是 JS 保留字，会导致桥接注册中断：" + "、".join(offenders)
        )


def main() -> None:
    resolve.install()
    api = Api()
    _assert_api_js_safe(api)
    window = webview.create_window(
        "Infinity",
        resource_path(os.path.join("web", "index.html")),
        js_api=api,
        width=1100,
        height=780,
        min_size=(860, 640),
        background_color="#2D2B3B",
    )
    api._window = window
    window.events.shown += _apply_native_icon
    webview.start()


if __name__ == "__main__":
    worker = _parse_patch_worker_argv(sys.argv)
    if worker is not None:
        action, result_path = worker
        raise SystemExit(run_patch_worker(action, result_path))
    main()
