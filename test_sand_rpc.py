"""sand_rpc unit tests (offline). Run: python test_sand_rpc.py"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

from sand_patch import (
    AGENT_HOST_MODULE_ANCHOR,
    SAND_AGENT_FLAGS_MARKER,
    TASK_TOOL_PROPS_REF,
    TASK_TOOL_PROPS_VOID,
    apply_agent_runtime_flags,
    apply_sand_rpc_lite,
    remove_agent_runtime_flags,
    remove_sand_rpc_lite,
)
from sand_rpc import (
    build_stream_request,
    create_cursor_checksum,
    envelope,
    iter_frames,
    walk_proto,
)


def _sample_js() -> str:
    return (
        "var n={d:function(t,o){Object.assign(t,o)}};var t={};"
        + AGENT_HOST_MODULE_ANCHOR
        + "function Loe(){}"
        + "const Roe={enableEmptyResponseRetry:!0,nalLoopDetection:!0};"
        + "var cfg={"
        + TASK_TOOL_PROPS_VOID
        + ",other:1,featureFlags:Roe};"
    )


def test_build_stream_request_has_conversation_id() -> None:
    conv = "11111111-2222-3333-4444-555555555555"
    payload = build_stream_request("hello", conversation_id=conv)
    fields = walk_proto(payload)
    field_nos = [fno for fno, _wire, _val in fields]
    assert 8 in field_nos
    assert any(
        isinstance(v, bytes) and conv.encode() in v
        for _fno, w, v in fields
        if w == 2
    )


def test_envelope_format() -> None:
    payload = b"\x08\x01\x12\x03foo"
    framed = envelope(payload, flags=0)
    assert framed[0] == 0
    length = struct.unpack(">I", framed[1:5])[0]
    assert length == len(payload)
    assert framed[5:] == payload


def test_create_cursor_checksum_deterministic() -> None:
    mid = "00000000-0000-0000-0000-000000000000"
    a = create_cursor_checksum(mid, now_ms=1_700_000_000_000)
    b = create_cursor_checksum(mid, now_ms=1_700_000_000_000)
    assert a == b
    assert a.endswith(mid)
    assert len(a) > len(mid)


def test_iter_frames_roundtrip() -> None:
    chunks = [b"\x08\x01", b"\x0a\x03bar", b"\x12\x00"]
    raw = b"".join(envelope(c, flags=0) for c in chunks)
    parsed = list(iter_frames(raw))
    assert len(parsed) == len(chunks)
    for (_flags, body), expected in zip(parsed, chunks):
        assert body == expected


def test_apply_sand_rpc_lite_on_sample() -> None:
    src = _sample_js()
    out, n = apply_sand_rpc_lite(src)
    assert n >= 1
    assert TASK_TOOL_PROPS_VOID not in out
    assert TASK_TOOL_PROPS_REF in out
    assert AGENT_HOST_MODULE_ANCHOR in out


def test_remove_sand_rpc_lite_reversible() -> None:
    src = _sample_js()
    patched, pn = apply_sand_rpc_lite(src)
    assert pn >= 1
    restored, rn = remove_sand_rpc_lite(patched)
    assert rn >= 1
    assert restored == src


def test_apply_sand_rpc_lite_refreshable() -> None:
    src = _sample_js()
    first, _n = apply_sand_rpc_lite(src)
    second, n2 = apply_sand_rpc_lite(first)
    assert n2 >= 1
    assert second == first
    assert "enableShellSubagent:!0" in second
    assert "modelsBySlug:new Map" in second
    assert 'subagentModelForcePolicy:"none"' in second
    assert "o||[]" not in second
    assert "getTaskToolConfig:async" in second


def test_apply_agent_runtime_flags_on_roe() -> None:
    src = _sample_js()
    out, n = apply_agent_runtime_flags(src)
    assert n >= 1
    assert SAND_AGENT_FLAGS_MARKER in out
    assert "useClientSideSubagent:!0" in out
    assert "enableExploreSubagent:!0" in out
    assert "defaultSubagentsRunInBackground:!1" in out
    assert "enableMultitaskMode:!0" in out
    assert "enableReadonlyShell:!0" in out
    assert "enableCloudAsyncSubagents" not in out
    restored, rn = remove_agent_runtime_flags(out)
    assert rn >= 1
    assert restored == src


def test_legacy_agent_flags_still_removed() -> None:
    src = (
        "const Roe={enableEmptyResponseRetry:!0"
        ",useClientSideSubagent:!0,enableNestedSubagents:!0,"
        "enableExploreSubagent:!0,enableAwaitForSubagents:!0"
        + SAND_AGENT_FLAGS_MARKER
        + "};featureFlags:Roe"
    )
    out, n = remove_agent_runtime_flags(src)
    assert n >= 1
    assert SAND_AGENT_FLAGS_MARKER not in out
    assert "useClientSideSubagent" not in out
    assert "const Roe={enableEmptyResponseRetry:!0};featureFlags:Roe" == out


def main() -> int:
    tests = [
        test_build_stream_request_has_conversation_id,
        test_envelope_format,
        test_create_cursor_checksum_deterministic,
        test_iter_frames_roundtrip,
        test_apply_sand_rpc_lite_on_sample,
        test_remove_sand_rpc_lite_reversible,
        test_apply_sand_rpc_lite_refreshable,
        test_apply_agent_runtime_flags_on_roe,
        test_legacy_agent_flags_still_removed,
    ]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"ok {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {exc}", file=sys.stderr)
    if failed:
        print(f"{failed} failed, {len(tests) - failed} passed", file=sys.stderr)
        return 1
    print(f"all {len(tests)} passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
