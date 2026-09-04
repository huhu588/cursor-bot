"""3.18.25 真实文件：server 模式 = SandClaimer 大账单分流，不强制本地循环。"""
from __future__ import annotations

from pathlib import Path

import pytest

import sand_patch as s

CURSOR_APP = Path(r"D:\GongJu\cursor\resources\app")
WB = CURSOR_APP / "out" / "vs" / "workbench" / "workbench.desktop.main.js"
HOST_DIST = CURSOR_APP / "extensions" / "cursor-agent-host" / "dist"


def _host_router() -> Path | None:
    for name in ("9909.js", "61.js", "478.js"):
        path = HOST_DIST / name
        if path.is_file():
            return path
    return None


HOST_ROUTER = _host_router()


pytestmark = pytest.mark.skipif(
    not WB.is_file() or HOST_ROUTER is None,
    reason="本机没有 Cursor workbench / agent-host 路由 bundle",
)


def test_hdrfix_v2_fn_splits_agent_vs_sand() -> None:
    fn = s.SAND_HDRFIX_V2_FN
    assert "AgentService" in fn
    assert 'return"ide"' in fn
    assert 'return"sand"' in fn


def test_31825_workbench_server_mode_has_unlocks_not_local_loop() -> None:
    src = WB.read_text(encoding="utf-8", errors="replace")
    out, stats = s.apply_server_mode_to_content(src)
    assert stats.model_unlock >= 3
    assert s.SAND_MODEL_UNLOCK_MARKER in out
    assert s.SAND_MEM_PRO_MARKER in out
    assert s.SAND_MAXMODE_MARKER in out
    assert s.SAND_HDRFIX_V2_MARKER in out
    assert s.SAND_MANAGED_LOCAL_ROUTE_MARKER not in out
    assert s.SAND_DIRECT_STREAM_MARKER not in out
    assert s.SAND_TASK_TOOL_PROPS_MARKER not in out
    restored, _ = s.remove_patch_from_content(out)
    assert restored == src


def test_31825_61js_agent_ide_and_cli_hdrfix() -> None:
    src = HOST_ROUTER.read_text(encoding="utf-8", errors="replace")
    out, _stats = s.apply_server_mode_to_content(src)
    assert s.SAND_HDRFIX_V2_MARKER in out or s.SAND_AGENT_IDE_MARKER in out
    assert s.SAND_MANAGED_LOCAL_ROUTE_MARKER not in out
    assert s.SAND_DIRECT_STREAM_MARKER not in out
    restored, _ = s.remove_patch_from_content(out)
    assert restored == src


def test_31825_membership_snippet_covers_unpaid_invoice() -> None:
    src = WB.read_text(encoding="utf-8", errors="replace")
    out, _stats = s.apply_server_mode_to_content(src)
    injected = s.SAND_MEMBERSHIP_SNIPPET + out
    assert s.SAND_MEMBERSHIP_MARKER in injected
    assert "has_unpaid_mid_month_invoice" in injected
    assert s.SAND_MANAGED_LOCAL_ROUTE_MARKER not in injected
