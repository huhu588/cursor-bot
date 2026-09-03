"""Windows UAC 提权：在无管理员 GUI 进程里拉起 --patch-worker 子进程。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_PATCH_WORKER_FLAG = "--patch-worker"
_RESULT_FLAG = "--result"


def state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return Path(base) / "SandClaimer"


def is_admin() -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return False


def app_launch_command() -> List[str]:
    """重新启动本应用（开发：python app.py；打包：SandClaimer.exe）。"""
    # PyInstaller 设置 sys.frozen；Nuitka 编译产物没有 frozen，但模块全局里有 __compiled__。
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return [sys.executable]
    app_py = Path(__file__).resolve().parent / "app.py"
    return [sys.executable, str(app_py)]


def _quote_win_arg(value: str) -> str:
    if not value or any(c in value for c in ' \t"'):
        return '"' + value.replace('"', '\\"') + '"'
    return value


_SEE_MASK_NOCLOSEPROCESS = 0x40
# 启动失败时不弹系统错误框（GUI 线程里会卡死等待），改为返回错误码。
_SEE_MASK_FLAG_NO_UI = 0x400
_WAIT_OBJECT_0 = 0
_STILL_ACTIVE = 259
# 用户在 UAC 上点「否」
_ERROR_CANCELLED = 1223


def _shell_execute_ex(verb: str, exe: str, params: str, show: int = 0) -> Tuple[Optional[int], int]:
    """ShellExecuteExW 启动进程并返回 (hProcess, GetLastError)。

    与 ShellExecuteW 不同，带 SEE_MASK_NOCLOSEPROCESS 能拿到进程句柄，
    这样 worker 没写结果文件就崩溃时也能及时察觉，而不是干等超时。
    失败时返回 (None, 错误码)；用户在 UAC 上点「否」时错误码为 1223。
    """
    import ctypes
    from ctypes import wintypes

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", wintypes.ULONG),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    # use_last_error：错误码在调用返回瞬间被 ctypes 捕获，不会被后续 WinAPI 调用冲掉。
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL

    info = SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS | _SEE_MASK_FLAG_NO_UI
    info.hwnd = None
    info.lpVerb = verb
    info.lpFile = exe
    info.lpParameters = params
    info.lpDirectory = None
    info.nShow = show
    ok = shell32.ShellExecuteExW(ctypes.byref(info))
    if not ok:
        return None, int(ctypes.get_last_error())
    return (int(info.hProcess) if info.hProcess else None), 0


def _kernel32():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _process_exit_code(hprocess: int) -> Optional[int]:
    """进程已退出返回退出码；仍在运行返回 None。"""
    import ctypes
    from ctypes import wintypes

    kernel32 = _kernel32()
    if kernel32.WaitForSingleObject(hprocess, 0) != _WAIT_OBJECT_0:
        return None
    code = wintypes.DWORD(0)
    if not kernel32.GetExitCodeProcess(hprocess, ctypes.byref(code)):
        return -1
    if code.value == _STILL_ACTIVE:
        return None
    return int(code.value)


def _close_handle(hprocess: Optional[int]) -> None:
    if not hprocess:
        return
    try:
        _kernel32().CloseHandle(hprocess)
    except Exception:
        pass


def _wait_worker_result(
    result_path: Path,
    hprocess: Optional[int],
    timeout: float,
    exit_grace: float = 2.0,
) -> Dict[str, Any]:
    """轮询结果文件；若拿到了进程句柄，进程退出后再等 exit_grace 秒仍无结果即判异常。"""
    deadline = time.time() + timeout
    exited_at: Optional[float] = None
    exit_code: Optional[int] = None
    while time.time() < deadline:
        if result_path.is_file():
            data: Any
            try:
                text = result_path.read_text(encoding="utf-8")
                data = json.loads(text)
            except Exception as exc:
                data = {"ok": False, "error": f"读取提权任务结果失败：{exc}"}
            try:
                result_path.unlink(missing_ok=True)
            except OSError:
                pass
            if isinstance(data, dict):
                return data
            return {"ok": False, "error": "提权任务返回格式无效"}
        if hprocess and exited_at is None:
            exit_code = _process_exit_code(hprocess)
            if exit_code is not None:
                exited_at = time.time()
        if exited_at is not None and time.time() - exited_at >= exit_grace:
            if exit_code == 0:
                # worker 正常结束却没有结果文件：多半是结果目录不可写，补丁本身可能已生效。
                return {
                    "ok": False,
                    "error": (
                        "提权任务已结束（code=0）但未写出结果文件，可能是结果目录不可写；"
                        "请点「查看补丁情况」确认补丁是否已生效"
                    ),
                }
            return {
                "ok": False,
                "error": (
                    f"提权任务异常退出（code={exit_code}），未返回结果；"
                    "请完全退出 Cursor 后重试，或运行 patch_install.bat"
                ),
            }
        time.sleep(0.25)

    return {
        "ok": False,
        "error": "提权安装超时。若已点「是」仍失败，请关闭 Cursor 后以管理员重试。",
    }


def run_elevated_patch_worker(action: str, timeout: float = 900.0) -> Dict[str, Any]:
    """弹出 UAC，以管理员运行 patch worker；阻塞直到结果 JSON 写入、进程异常退出或超时。"""
    if sys.platform != "win32":
        return {
            "ok": False,
            "error": "自动提权目前仅支持 Windows；请右键「以管理员身份运行」本工具。",
        }

    state_dir().mkdir(parents=True, exist_ok=True)
    result_path = state_dir() / f"patch_job_{os.getpid()}_{int(time.time() * 1000)}.json"
    try:
        result_path.unlink(missing_ok=True)
    except OSError:
        pass

    cmd = app_launch_command() + [
        _PATCH_WORKER_FLAG,
        action,
        _RESULT_FLAG,
        str(result_path),
    ]
    exe = cmd[0]
    params = " ".join(_quote_win_arg(part) for part in cmd[1:])

    # SW_HIDE：worker 只写结果文件，不另开控制台
    hprocess, err = _shell_execute_ex("runas", exe, params, show=0)
    if hprocess is None and err:
        if err == _ERROR_CANCELLED:
            return {"ok": False, "error": "已取消 UAC 授权，未执行任何修改。"}
        return {
            "ok": False,
            "error": f"UAC 提权失败（code={err}）。可右键以管理员运行本工具，或运行 patch_install.bat。",
        }

    try:
        return _wait_worker_result(result_path, hprocess, timeout)
    finally:
        _close_handle(hprocess)


def needs_elevation_for_patch() -> bool:
    """改 Cursor 安装目录与系统 hosts 在 Windows 上通常需要管理员。"""
    return sys.platform == "win32" and not is_admin()
