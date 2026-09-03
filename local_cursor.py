"""读取本机 Cursor 客户端的登录态（token/邮箱/套餐），用于「以本机账号探测」。

Cursor 把登录信息存在 SQLite 库 state.vscdb 的 ItemTable 键值表里：
  - cursorAuth/accessToken        当前登录的 access_token（JWT）
  - cursorAuth/refreshToken       续期用 refresh_token（可能没有）
  - cursorAuth/cachedEmail        缓存邮箱
  - cursorAuth/stripeMembershipType 套餐（free/pro/enterprise…）
只读打开（mode=ro&immutable=1）：Cursor 正在运行时库被占用也能读，且绝不写盘。

切号写入（write_local_account）会在同一事务里先清空全部 cursorAuth/* 再写新快照，
避免旧号的 refreshToken / stripeMembershipType 等残留把登录态刷回上一个账号。
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
import uuid

_KEYS = {
    "token": "cursorAuth/accessToken",
    "refresh": "cursorAuth/refreshToken",
    "email": "cursorAuth/cachedEmail",
    "membership": "cursorAuth/stripeMembershipType",
}

_WRITE_SIGNUP_TYPE = "Auth"


def _cursor_root() -> str:
    """本机 Cursor 数据根目录（Windows / macOS / Linux）。"""
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "Cursor")


def state_db_path() -> str:
    """本机 Cursor state.vscdb 路径。"""
    return os.path.join(_cursor_root(), "User", "globalStorage", "state.vscdb")


def storage_json_path() -> str:
    """本机 Cursor storage.json 路径（机器码 telemetry.* 存这里）。"""
    return os.path.join(_cursor_root(), "User", "globalStorage", "storage.json")


def machineid_path() -> str:
    """本机 Cursor machineid 文件路径（= storage.serviceMachineId）。"""
    return os.path.join(_cursor_root(), "machineid")


def read_local_account() -> dict | None:
    """返回 {token, refresh, email, membership}；未登录 / 读不到 token 时返回 None。refresh 可能为 None。"""
    path = state_db_path()
    if not os.path.isfile(path):
        return None
    uri = "file:{}?mode=ro&immutable=1".format(path.replace("\\", "/"))
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    except Exception:
        return None
    try:
        out = {}
        for field, key in _KEYS.items():
            try:
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key=?", (key,)
                ).fetchone()
            except Exception:
                row = None
            out[field] = row[0] if row else None
    finally:
        conn.close()
    if not out.get("token"):
        return None
    for field in ("token", "refresh"):
        value = out.get(field)
        if isinstance(value, bytes):
            out[field] = value.decode("utf-8", "replace")
    if not out.get("refresh"):
        out["refresh"] = None
    return out


def local_user_id() -> str | None:
    """从本机 Cursor 登录 JWT 解析 user_id；未登录时返回 None。"""
    acct = read_local_account()
    if not acct or not acct.get("token"):
        return None
    try:
        from sand_api import parse_token

        user_id, _jwt, _claims = parse_token(acct["token"])
        return user_id
    except Exception:
        return None


def write_local_account(
    access_token: str,
    email: str,
    refresh_token: str | None = None,
    membership: str | None = None,
) -> None:
    """把账号写入本机 Cursor 登录态（切号）。必须在 Cursor 已关闭时调用，否则库被锁。

    与 cursor-byok 的 ApplyCursorAuthSnapshot 对齐：在同一事务里先
    `DELETE FROM ItemTable WHERE key LIKE 'cursorAuth/%'` 清掉旧号的全部登录态
    （含 refreshToken / stripeMembershipType / cachedSignUpType 等），再写入新快照：
      - cursorAuth/accessToken、cursorAuth/cachedEmail、cursorAuth/cachedSignUpType="Auth"
      - 有 refresh_token 才写 cursorAuth/refreshToken；没有则保持删除状态，
        避免 Cursor 用旧号的 refresh 刷新回上一个账号（此时 access_token 到期前有效）
      - 有 membership 才写 cursorAuth/stripeMembershipType
      - cursor.accessToken / cursor.email 照旧写入（不在 cursorAuth/ 前缀下，单独覆盖）
    任一步失败整体回滚，不会留下半写状态。
    """
    path = state_db_path()
    if not os.path.isfile(path):
        raise RuntimeError("未找到本机 Cursor state.vscdb（可能未安装或未登录过）")
    conn = sqlite3.connect(path, timeout=8)
    try:
        cur = conn.cursor()

        def put(key: str, value: str) -> None:
            cur.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                (key, value),
            )

        # DELETE 会隐式开启事务，后续 INSERT 都在同一事务内，commit 一次性落盘。
        cur.execute("DELETE FROM ItemTable WHERE key LIKE 'cursorAuth/%'")
        put("cursorAuth/accessToken", access_token)
        put("cursorAuth/cachedEmail", email or "")
        put("cursorAuth/cachedSignUpType", _WRITE_SIGNUP_TYPE)
        if refresh_token:
            put("cursorAuth/refreshToken", refresh_token)
        if membership:
            put("cursorAuth/stripeMembershipType", membership)
        put("cursor.accessToken", access_token)
        put("cursor.email", email or "")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def cursor_process_running(exe_name: str) -> bool | None:
    """Windows 上用 tasklist 判断指定映像名的进程是否仍在。

    返回 True=仍在运行，False=已退出，None=无法判断（非 Windows 或 tasklist 调用失败）。
    """
    if os.name != "nt":
        return None
    name = (exe_name or "").strip() or "Cursor.exe"
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return _tasklist_csv_has_image(result.stdout or "", name)


def _tasklist_csv_has_image(stdout: str, name: str) -> bool:
    """按行解析 `tasklist /NH /FO CSV` 输出，第一列（映像名）与 name 精确、不区分大小写相等才算命中。

    不再用子串匹配：避免 "Cursor.exe" 被 "MyCursor.exe" 之类误命中，也避免
    「INFO: 没有运行的任务匹配指定标准」提示行里的文字干扰。
    """
    want = name.strip().lower()
    for row in csv.reader(io.StringIO(stdout)):
        if not row:
            continue
        image = (row[0] or "").strip().lower()
        if image == want:
            return True
    return False


# Windows 上 tasklist 连续返回 None（无法判断）的最大重试次数。
_WAIT_UNKNOWN_RETRIES = 3


def wait_cursor_exited(exe_name: str, timeout: float = 8.0, interval: float = 0.25) -> bool | None:
    """轮询等待 Cursor 进程真正退出（最多 timeout 秒）。

    返回：
      - True   确认已退出（非 Windows 无法探测时直接放行）
      - False  超时后进程仍在运行
      - None   Windows 上 tasklist 不可用，连续 _WAIT_UNKNOWN_RETRIES 次都无法确认
    切号前必须确认退出，否则 state.vscdb 被占用会写失败或写入后被 Cursor 用内存态覆盖；
    因此 Windows 上「无法确认」不能当成已退出放行，由调用方决定放弃写入。
    """
    if os.name != "nt":
        return True
    deadline = time.monotonic() + max(0.0, float(timeout))
    unknown = 0
    while True:
        running = cursor_process_running(exe_name)
        if running is False:
            return True
        if running is None:
            unknown += 1
            if unknown >= _WAIT_UNKNOWN_RETRIES:
                return None
        else:
            unknown = 0
            if time.monotonic() >= deadline:
                return False
        time.sleep(max(0.05, float(interval)))


def _rand_hex64() -> str:
    return os.urandom(32).hex()


def _atomic_write(path: str, data: bytes) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.replace(tmp, path)


def reset_machine_ids() -> dict:
    """重置本机机器码，防止多个小号被 Cursor 关联。必须在 Cursor 已关闭时调用。

    覆盖三处（均实测确认）：
      - storage.json：telemetry.machineId / macMachineId（64位hex）、devDeviceId（UUID）、sqmId（{大写GUID}）
      - state.vscdb：storage.serviceMachineId（UUID）
      - machineid 文件（= serviceMachineId）

    返回字典含 machineIdFileWritten：machineid 文件是否写成功（失败为 False，不再静默吞掉，
    由调用方决定是否提示用户）。storage.json / state.vscdb 写失败则直接抛错。
    """
    service_id = str(uuid.uuid4())
    ids = {
        "telemetry.machineId": _rand_hex64(),
        "telemetry.macMachineId": _rand_hex64(),
        "telemetry.devDeviceId": str(uuid.uuid4()),
        "telemetry.sqmId": "{" + str(uuid.uuid4()).upper() + "}",
    }

    sj = storage_json_path()
    data = {}
    if os.path.isfile(sj):
        try:
            with open(sj, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            data = {}
    if not isinstance(data, dict):
        data = {}
    data.update(ids)
    _atomic_write(sj, json.dumps(data, ensure_ascii=False, indent=4).encode("utf-8"))

    db = state_db_path()
    if os.path.isfile(db):
        conn = sqlite3.connect(db, timeout=8)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
                ("storage.serviceMachineId", service_id),
            )
            conn.commit()
        finally:
            conn.close()

    machineid_written = True
    try:
        _atomic_write(machineid_path(), service_id.encode("utf-8"))
    except Exception:
        machineid_written = False

    return {
        "machineId": ids["telemetry.machineId"],
        "devDeviceId": ids["telemetry.devDeviceId"],
        "serviceMachineId": service_id,
        "machineIdFileWritten": machineid_written,
    }
