"""sand_rpc unit tests (offline). Run: python test_sand_rpc.py"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

from sand_patch import (
    AGENT_HOST_MODULE_ANCHOR,
    SAND_AGENT_FLAGS_MARKER,
    SAND_TASK_TOOL_PROPS_MARKER,
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


def test_agent_flags_match_renamed_object() -> None:
    """3.18.25 把 featureFlags 对象从 Roe 改名为 xre；按字段签名匹配，不能依赖变量名。"""
    src = (
        "const xre={enableEmptyResponseRetry:!0,enableGrepBroadGlobGuard:!0,"
        "enableReadToolNegativeOffset:!0,enableSandboxSharedBuildCache:!0,"
        "nalLoopDetection:!0};var c={agentType:1,featureFlags:xre,isDev:!1};"
    )
    out, n = apply_agent_runtime_flags(src)
    assert n >= 1
    assert "useClientSideSubagent:!0" in out
    assert "enableMultitaskMode:!0" in out
    assert out.count(SAND_AGENT_FLAGS_MARKER) == 1
    again, _ = apply_agent_runtime_flags(out)
    assert again == out
    restored, _ = remove_agent_runtime_flags(out)
    assert restored == src


def test_agent_flags_skipped_when_object_unreferenced() -> None:
    """签名对上但没有 featureFlags:<名> 引用时不注入，避免误伤同形态对象。"""
    src = (
        "const zzz={enableEmptyResponseRetry:!0,enableGrepBroadGlobGuard:!0,"
        "nalLoopDetection:!0};var c={agentType:1};"
    )
    out, n = apply_agent_runtime_flags(src)
    assert n == 0
    assert out == src


def test_319_feature_flags_be_fallback() -> None:
    """3.19.7 const be={...enableEmptyResponseRetry 在中间...} 且用 ?l:be 引用。"""
    src = (
        "const be={disableBackgroundTaskFollowUp:!1,enableAwaitForSubagents:!0,"
        "enableEmptyResponseRetry:!0,nalLoopDetection:!0,useClientSideSubagent:!0};"
        "const g=null!==(l=t.featureFlags)&&void 0!==l?l:be;"
    )
    out, n = apply_agent_runtime_flags(src)
    assert n >= 1
    assert SAND_AGENT_FLAGS_MARKER in out
    assert "enableMultitaskMode:!0" in out
    assert "enableReadonlyShell:!0" in out
    restored, _ = remove_agent_runtime_flags(out)
    assert restored == src


def test_319_task_throw_replaced() -> None:
    src = (
        "n.d(t,{createAgentHost:()=>ot});"
        "function Ae(e){return{getTaskToolConfig:()=>Ne(this,void 0,void 0,function*(){"
        'throw new Error("managed local loop does not build in-process child AgentConfig")}),'
        "modelInfo:n}}"
    )
    out, n = apply_sand_rpc_lite(src)
    assert n >= 1
    assert SAND_TASK_TOOL_PROPS_MARKER in out
    assert "getTaskToolConfig:async(e,t)=>{" in out
    assert "managed local loop does not build" in out
    restored, _ = remove_sand_rpc_lite(out)
    assert restored == src
    again, _ = apply_sand_rpc_lite(out)
    assert again == out


def test_317_createAgentHost_solo_export_still_matches() -> None:
    """3.17.21 的 n.d(t,{createAgentHost:()=>Loe}); 不能被 3.19 的宽匹配挤掉。"""
    src = _sample_js()
    assert "n.d(t,{createAgentHost:()=>Loe});" in src
    out, n = apply_sand_rpc_lite(src)
    assert n >= 1
    assert TASK_TOOL_PROPS_REF in out
    restored, _ = remove_sand_rpc_lite(out)
    assert restored == src


def test_stream_mode_keeps_317_whitelist_and_allows_319() -> None:
    from sand_patch import PatchStatus

    def status(**extra: object) -> PatchStatus:
        base = dict(
            client_markers=1,
            eligibility_markers=0,
            ide_matches=0,
            external_sand_matches=0,
            external_marker_count=0,
            legacy_client_markers=0,
            legacy_eligibility_markers=0,
            patched_files=(),
            managed_local_route_markers=1,
            local_runtime_load_markers=1,
            move_exec_markers=1,
            agent_host_enablement_markers=1,
            agent_host_identity_markers=1,
        )
        base.update(extra)
        return PatchStatus(**base)  # type: ignore[arg-type]

    incomplete_317 = status(cursor_version="3.17.21")
    assert incomplete_317.stream_mode_installed is False
    complete_317 = status(
        cursor_version="3.17.21",
        model_route_markers=1,
        local_model_markers=1,
    )
    assert complete_317.stream_mode_installed is True
    complete_318 = status(cursor_version="3.18.25")
    assert complete_318.stream_mode_installed is True
    complete_319 = status(cursor_version="3.19.7")
    assert complete_319.stream_mode_installed is False
    complete_319_stream = status(cursor_version="3.19.7", direct_stream_markers=1)
    assert complete_319_stream.stream_mode_installed is True


def test_supported_cursor_versions_keep_old_and_add_319() -> None:
    from sand_patch import STREAM_CURSOR_VERSION, STREAM_CURSOR_VERSIONS

    assert STREAM_CURSOR_VERSIONS[:3] == ("3.17.21", "3.18.9", "3.18.25")
    assert "3.19.7" in STREAM_CURSOR_VERSIONS
    assert STREAM_CURSOR_VERSION == "3.19.7"


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
        test_agent_flags_match_renamed_object,
        test_agent_flags_skipped_when_object_unreferenced,
        test_319_feature_flags_be_fallback,
        test_319_task_throw_replaced,
        test_317_createAgentHost_solo_export_still_matches,
        test_stream_mode_keeps_317_whitelist_and_allows_319,
        test_supported_cursor_versions_keep_old_and_add_319,
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
