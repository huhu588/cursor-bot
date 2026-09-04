"""Patch apply/rollback tests. Run: python test_hdrfix_migration.py"""
from __future__ import annotations

import sys

from sand_patch import (
    SAND_CLIENT_VERSION,
    SAND_HDRFIX_MARKER,
    apply_patch_to_content,
    remove_patch_from_content,
)

LIVE_ORPHAN = (
    'e.header.set("x-cursor-client-type","ide")/*SAND_HDRFIX_V1*/,'
    'f!==void 0&&e.header.set("x-cursor-client-layout",f)'
)
ORIGINAL = (
    'e.header.set("x-cursor-client-type",g??"ide"),'
    'f!==void 0&&e.header.set("x-cursor-client-layout",f)'
)
GET_TYPE = 'getDesktopBackendClientType(){return this.environmentService.isGlass?"glass":"ide"}'
AUTH = (
    'getDesktopBackendClientType(),[lLi]:this.productService.version,[aLi]:oLi(t)'
)
MAIN_OBJ = '{"x-cursor-client-type":"ide","x-cursor-client-version":this.productService.version}'


def test_orphan_live() -> None:
    out, _ = apply_patch_to_content(LIVE_ORPHAN)
    assert '"sand"' in out
    assert "x-sand-box-namespace" in out
    assert "0.18.0" not in out
    assert ")/*SAND_HDRFIX_V1*/" not in out
    restored, _ = remove_patch_from_content(out)
    assert 'header.set("x-cursor-client-type","ide")' in restored
    assert SAND_HDRFIX_MARKER not in restored
    assert "x-sand-box-namespace" not in restored


def test_original_g_fallback() -> None:
    out, _ = apply_patch_to_content(ORIGINAL)
    assert 'header.set("x-cursor-client-type","sand"' in out
    assert "x-sand-box-namespace" in out
    assert "0.18.0" not in out
    restored, _ = remove_patch_from_content(out)
    assert restored == ORIGINAL, (ORIGINAL, restored)


def test_get_type_and_version() -> None:
    src = GET_TYPE + AUTH
    out, _ = apply_patch_to_content(src)
    assert "isGlass?\"sand\"" in out.replace(" ", "")
    assert "this.productService.version" in out
    restored, _ = remove_patch_from_content(out)
    assert 'isGlass?"glass":"ide"' in restored
    assert "this.productService.version" in restored


def test_main_object() -> None:
    out, _ = apply_patch_to_content(MAIN_OBJ)
    assert '"x-cursor-client-type":"sand"' in out
    restored, _ = remove_patch_from_content(out)
    assert restored == MAIN_OBJ, (MAIN_OBJ, restored)


def test_idempotent() -> None:
    once, _ = apply_patch_to_content(ORIGINAL)
    twice, _ = apply_patch_to_content(once)
    assert twice == once


def test_agent_host_identity_roundtrip() -> None:
    src = 'Go=await P("Failed to create agent host",()=>l({network:{kind:ni,credentialManager:new To,clientIdentity:{clientType:"ide"},createNetworkHost:e=>a.createPlatformAgentHostNetworkHost(f,{clientIdentity:e.clientIdentity})}'
    out, stats = apply_patch_to_content(src)
    assert stats.agent_host_identity == 1
    assert 'clientType:"sand"/*SAND_AGENT_HOST_IDENTITY_V1*/' in out
    restored, rst = remove_patch_from_content(out)
    assert rst.agent_host_identity == 1
    assert restored == src


def test_agent_host_enablement_roundtrip() -> None:
    src = "this._agentHostEnabled=n,t.info(`[CursorAgentHostEnablementService] cursor_agent_host gate is ${n?"
    out, stats = apply_patch_to_content(src)
    assert stats.agent_host_enablement == 1
    assert "n=!0;/*SAND_AGENT_HOST_ENABLEMENT_V1*/this._agentHostEnabled=n," in out
    restored, rst = remove_patch_from_content(out)
    assert rst.agent_host_enablement == 1
    assert restored == src


def test_direct_stream_3189_anchor() -> None:
    src = "function hre(e){return t=>{return n=this,o=void 0,s=function*(){const z=1;"
    out, stats = apply_patch_to_content(src)
    assert stats.direct_stream == 1
    assert "/*SAND_DIRECT_INFERENCE_STREAM_V1*/" in out
    assert "new Joe(e,n,void 0,void 0).getSession()" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.direct_stream == 1
    assert restored == src


def test_direct_stream_skipped_on_317() -> None:
    src = "function I8g(e,t,n){return async function(i,r){const s=await e.stream(t,n);"
    out, stats = apply_patch_to_content(src)
    assert stats.direct_stream == 0
    assert "/*SAND_DIRECT_INFERENCE_STREAM_V1*/" not in out


def test_direct_stream_3197_ve_anchor() -> None:
    src = (
        "class J{constructor(e,t,n,o){this.client=e,this.requestedModel=t"
        ",this.modelConfig=n,this.inferenceReason=o}"
        "getSession(e){return 1}}"
        "new o.Ycw(x);"
        "function ve(e){return t=>{return n=this,r=void 0,s=function*(){const z=1;"
        'retryLogTag:"managed_local_agent_retries",'
        'reconnectEndpoint:"InferenceService.RunInference"'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.direct_stream == 1
    assert "/*SAND_DIRECT_INFERENCE_STREAM_V1*/" in out
    assert "new J(e,n,void 0,void 0).getSession()" in out
    assert "new o.Ycw(s.getExecutor(e))" in out
    assert "resolvedModelMetadata:{promptModelInfo:oe(a,mid)}" in out
    assert "resolvedModelMetadata:void 0" not in out
    assert "new Joe(" not in out
    assert "new RK(" not in out
    assert 'reconnectEndpoint:"InferenceService.Stream"/*SAND_RECONNECT_STREAM_V1*/' in out
    assert 'reconnectEndpoint:"InferenceService.RunInference"' not in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert rst.direct_stream == 1
    assert restored == src


def test_317_local_loop_roundtrip() -> None:
    src = (
        'let t=!1;try{t=await n.cursor.checkFeatureGate(Mo)}catch(e){'
        'F.error("Failed to evaluate agent_host_local_loop; using backend NAL",e)}'
        "if(!t)return e;"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.local_runtime_load == 1
    assert "let t=!0;/*SAND_LOCAL_RUNTIME_LOAD_V1*/" in out
    assert "checkFeatureGate(Mo)" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.local_runtime_load == 1
    assert restored == src


def test_318_local_runtime_roundtrip() -> None:
    src = "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}catch(e){t=!1}"
    out, stats = apply_patch_to_content(src)
    assert stats.local_runtime_load == 1
    restored, rst = remove_patch_from_content(out)
    assert restored == src


def test_317_move_exec_roundtrip() -> None:
    src = (
        '}(a.createAgentHost),p=await Promise.resolve(n.cursor.checkFeatureGate(xo)).catch(()=>!1),'
        "A=await async function(){try{return await n.cursor.checkFeatureGate(Oo)}catch{return!1}}(),"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.move_exec == 1
    assert "/*SAND_MOVE_EXEC_V1*/" in out
    assert "p=(!0/*SAND_MOVE_EXEC_V1*/" in out
    assert "checkFeatureGate(xo)" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.move_exec == 1
    assert restored == src


def test_478_namespace_roundtrip() -> None:
    src = (
        'i.header.set("x-cursor-client-type",null!==(s=null==r?void 0:r.clientType)'
        '&&void 0!==s?s:"cli"),n&&i.header.set("x-cursor-client-key",n)'
    )
    out, stats = apply_patch_to_content(src)
    assert 'x-sand-box-namespace","prod"' in out
    restored, _ = remove_patch_from_content(out)
    assert restored == src


def test_317_model_route_roundtrip() -> None:
    src = (
        'e.simulatedUserMessage?"simulated-message-not-supported":'
        'e.modelId!==v.w?"model-not-supported":e.hasModelCredentials?'
        '"private-model-not-supported":void 0'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.model_route == 1
    assert "/*SAND_MODEL_ROUTE_V1*/" in out
    assert "!1/*SAND_MODEL_ROUTE_V1*/" in out
    assert 'e.modelId!==v.w?"model-not-supported":' in out
    restored, rst = remove_patch_from_content(out)
    assert rst.model_route == 1
    assert restored == src


def test_478_mode_route_roundtrip() -> None:
    src = (
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        'e.requestedMode!==w.xyI.AGENT?"mode-not-supported":'
        'e.simulatedUserMessage?"simulated-message-not-supported":void 0'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.sand_rpc >= 2
    assert "/*SAND_MODE_ROUTE_V1*/" in out
    assert (
        "!1/*SAND_MODE_ROUTE_V1*//*SAND_MODE_ROUTE_RB:"
        'e.requestedMode!==w.xyI.AGENT*/?"mode-not-supported":'
    ) in out
    assert out.count('"mode-not-supported"') == 1
    # 动作闸门放宽到 managed-local 已注册的 12 种 case
    assert "/*SAND_ACTION_ROUTE_V1*/" in out
    assert '!["userMessageAction","subscriptionNotificationAction"' in out
    assert '"backgroundSubagentAction"].includes(e.actionCase)' in out
    assert out.count('"action-not-supported"') == 1
    # 幂等：再打一次不重复注入
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert rst.sand_rpc >= 2
    assert restored == src


def test_318_http2_gate_roundtrip() -> None:
    """3.18.x 的 HTTP/2 闸门排在最前，命中就走 connect（sand 必失败），需折成注释。"""
    src = (
        'if(!t.managedLocalAvailable)return"managed-local-unavailable";'
        "try{if(!1===(null===(n=t.isManagedInferenceHttp2Available)||void 0===n?"
        'void 0:n.call(t)))return"managed-local-http2-unavailable"}'
        'catch(e){return"managed-local-http2-unavailable"}'
        'return"userMessageAction"!==e.actionCase?"action-not-supported":void 0'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.sand_rpc >= 1
    assert "/*SAND_HTTP2_GATE_V1*/" in out
    # 原文整段被折进 RB 注释：闸门代码只出现在 marker 之后的注释里，不再是活代码
    head, _sep, tail = out.partition("/*SAND_HTTP2_GATE_V1*/")
    assert "managed-local-http2-unavailable" not in head
    assert tail.startswith("/*SAND_HTTP2_GATE_RB:")
    body, _sep2, rest = tail.partition("*/")
    assert "isManagedInferenceHttp2Available" in body
    assert "managed-local-http2-unavailable" not in rest
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, _rst = remove_patch_from_content(out)
    assert restored == src


def test_478_mode_route_legacy_form_migrates() -> None:
    """2.2.2/2.2.3 装的是「仅放行 0/undefined」形态，重装应升级为 !1 形态，卸载也能还原。"""
    legacy = (
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        "(void 0!==e.requestedMode&&0!==e.requestedMode&&e.requestedMode!==w.xyI.AGENT)"
        "/*SAND_MODE_ROUTE_V1*//*SAND_MODE_ROUTE_RB:e.requestedMode!==w.xyI.AGENT*/"
        '?"mode-not-supported":e.simulatedUserMessage?"x":void 0'
    )
    pristine = (
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        'e.requestedMode!==w.xyI.AGENT?"mode-not-supported":e.simulatedUserMessage?"x":void 0'
    )
    upgraded, _ = apply_patch_to_content(legacy)
    assert "0!==e.requestedMode" not in upgraded
    assert '!1/*SAND_MODE_ROUTE_V1*/' in upgraded
    assert upgraded.count("/*SAND_MODE_ROUTE_V1*/") == 1
    restored, _ = remove_patch_from_content(legacy)
    assert restored == pristine
    restored2, _ = remove_patch_from_content(upgraded)
    assert restored2 == pristine


def test_477_local_agent_config_roundtrip() -> None:
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from sand_patch import DOE_TAIL_ORIGINAL, MODEL_INFO_ORIGINAL, MODEL_INFO_PATCHED

    src = (
        "function Doe(e){var t;const n=Object.assign(Object.assign({},f(Poe.w,"
        '"other","latest")),' + MODEL_INFO_ORIGINAL + "),o={modelInfo:n};"
        "return Object.assign(Object.assign({},g(o)),{maxSteps:128,modelInfo:n"
        + DOE_TAIL_ORIGINAL
    )
    out, stats = apply_patch_to_content(src)
    assert stats.local_agent == 2
    assert "/*SAND_BG_SUMMARY_V1*/" in out
    assert "unusedPercentTokensThresholdToStartBackgroundSummarization:.1" in out
    assert "/*SAND_MODEL_INFO_V1*/" in out
    assert MODEL_INFO_ORIGINAL not in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert rst.local_agent >= 2
    assert restored == src

    node = shutil.which("node")
    if not node:
        print("skip: node not available for modelInfo runtime check")
        return
    script = (
        "const run=(e)=>" + MODEL_INFO_PATCHED + ";"
        "const pick=(o)=>[o.vendor,o.modelName,o.isClaude4X,o.isOpus5,o.isFable5,o.isOpus46,"
        "o.isGemini3,o.isGrok45ProductPrompt,o.reasoningEffort];"
        "console.log(JSON.stringify(["
        "pick(run({modelId:'claude-fable-5-1',requestedModel:{parameters:[{id:'effort',value:'high'}]}})),"
        "pick(run({modelId:'claude-opus-5'})),"
        "pick(run({modelId:'claude-4.6-opus'})),"
        "pick(run({modelId:'grok-4.6'})),"
        "pick(run({modelId:'gemini-3.1-pro'})),"
        "pick(run({modelId:'gpt-5.6'})),"
        "pick(run({modelId:undefined}))]));"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = Path(fh.name)
    try:
        proc = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
    finally:
        path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    rows = json.loads(proc.stdout.strip())
    assert rows[0] == ["anthropic", "claude-fable-5-1", True, False, True, False, False, False, "high"]
    assert rows[1][:5] == ["anthropic", "claude-opus-5", True, True, False]
    assert rows[2][0] == "anthropic" and rows[2][5] is True
    assert rows[3][0] == "xai" and rows[3][2] is False and rows[3][7] is True
    assert rows[4][0] == "gemini" and rows[4][6] is True
    # GPT 未知家族：保持原 Claude 行为（vendor anthropic、isClaude4X true）
    assert rows[5][0] == "anthropic" and rows[5][2] is True
    assert rows[6] == ["anthropic", "claude-sonnet-4-6", True, False, False, False, False, False, None]


def test_477_ctx_window_roundtrip() -> None:
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from sand_patch import (
        AGENT_HOST_MODULE_ANCHOR,
        CTX_WINDOW_DECL,
        CTX_WINDOW_USAGE_ORIGINAL,
    )

    src = (
        "var n={d:function(){}};var t={};"
        + AGENT_HOST_MODULE_ANCHOR
        + "function Loe(){}class X{constructor(m){this.requestedModel=m}run(t,n){"
        + CTX_WINDOW_USAGE_ORIGINAL
        + "}}"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.ctx_window == 2
    assert out.count("/*SAND_CTX_WINDOW_V1*/") == 2
    assert CTX_WINDOW_DECL in out
    assert "maxTokens:_sandCtxWin(n.maxTokens,this.requestedModel)" in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert rst.ctx_window >= 2
    assert restored == src

    node = shutil.which("node")
    if not node:
        print("skip: node not available for ctx-window runtime check")
        return
    script = (
        "globalThis.n={d:function(){}};globalThis.t={};"
        + CTX_WINDOW_DECL
        + "const cases=[[300000,{parameters:[{id:'context',value:'1m'}]}],"
        "[300000,{parameters:[{id:'context',value:'300k'}]}],"
        "[300000,{parameters:[{id:'thinking',value:'true'}]}],"
        "[300000,{parameters:[{id:'context',value:'weird'}]}],"
        "[300000,undefined],[272000,{parameters:[{id:'context',value:'200K'}]}]];"
        "console.log(JSON.stringify(cases.map(([a,b])=>_sandCtxWin(a,b))));"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = Path(fh.name)
    try:
        proc = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
    finally:
        path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip()) == [1000000, 300000, 300000, 300000, 300000, 200000]


def test_server_mode_hybrid_identity_and_unlocks() -> None:
    from sand_patch import PATCH_MODE_SERVER, apply_server_mode_to_content

    src = (
        'header.set("x-cursor-client-type",e??"ide");'
        "function abc(e){const{adminSettingsService:x}=e;return x}"
        "hasResolvedTeamMembership:a,teamId:b}){return c===d.FREE&&e&&f===void 0}"
        "_membershipType=()=>this.storageService.get(1);"
        "hasValidPaymentMethod=async()=>{return await x()};"
        'try{return(yield o.checkFeatureGate(J))?{runtime:"managed-local",reason:"eligible"}:'
        '{runtime:"connect",reason:"gate-off"}}catch(e){return 1}'
        'o.header.set("x-cursor-client-type","ide");'
        "return{headers:a,credentialFingerprint:1};"
    )
    local_out, local_stats = apply_patch_to_content(src)
    assert local_stats.managed_local_route == 1
    server_out, server_stats = apply_server_mode_to_content(local_out)
    assert "/*SAND_MANAGED_LOCAL_ROUTE_V1*/" not in server_out
    assert "/*SAND_HDRFIX_V2*/" in server_out
    assert "/*SAND_AGENT_IDE_V1*/" in server_out
    assert 'reason:"gate-off"' in server_out
    assert '"sand-client"' not in server_out
    assert server_stats.model_unlock == 3
    for marker in ("/*SAND_MODEL_UNLOCK_V1*/", "/*SAND_MEM_PRO_V1*/", "/*SAND_MAXMODE_V1*/"):
        assert marker in server_out, marker
    direct, _ = apply_server_mode_to_content(src)
    assert "/*SAND_HDRFIX_V2*/" in direct
    again, _ = apply_patch_to_content(server_out, mode=PATCH_MODE_SERVER)
    assert again == server_out
    restored, _ = remove_patch_from_content(server_out)
    assert restored == src


def test_retry_resilience_roundtrip() -> None:
    import json
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    src = (
        "runOptions:{conversationId:t,subagentTypeName:n.subagentType||void 0,"
        "subagentModelOverrides:[],enableAgentRetries:!1},modelDetails:p;"
        'retryLogTag:"managed_local_agent_retries",reconnectEndpoint:"InferenceService.Stream",'
        'class rt{query(e,t,n,r){if(this.closed)throw new Error("Agent host interaction registry is closed");'
        "const m=`${t}:${n.id}`;return m}}"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.sand_rpc >= 3
    assert "enableAgentRetries:!0/*SAND_SUBAGENT_RETRY_V1*/}" in out
    assert 'maxRetries:8/*SAND_MAX_RETRIES_V1*/,reconnectEndpoint:"InferenceService.Stream"' in out
    assert "n.id||(n.id=this._sandQid=(this._sandQid||0)+1)/*SAND_INTERACTION_ID_V1*/;const m=" in out
    assert "enableAgentRetries:!1" not in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert rst.sand_rpc >= 3
    assert restored == src

    node = shutil.which("node")
    if not node:
        print("skip: node not available for interaction-id runtime check")
        return
    # 同一 turn 内两个 id=0 的 query 必须得到不同 key；已有 id 的 query 保持不变
    script = (
        out[out.index("class rt") :]
        + ";const r=new rt();const q1={id:0},q2={id:0},q3={id:7};"
        "console.log(JSON.stringify([r.query({},'T',q1),r.query({},'T',q2),r.query({},'T',q3),q1.id,q2.id,q3.id]));"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = Path(fh.name)
    try:
        proc = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
    finally:
        path.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip()) == ["T:1", "T:2", "T:7", 1, 2, 7]


def test_478_subagent_run_options_roundtrip() -> None:
    src = (
        "hasUnsupportedRunOptions:void 0!==e.runOptions.customSystemPrompt"
        "||void 0!==e.runOptions.harness||!0===e.runOptions.excludeWorkspaceContext"
        "||void 0!==e.runOptions.subagentTypeName||void 0!==e.runOptions.parentAgentToolCallId"
        "||!0===e.runOptions.directMetaParentChildSubagent"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.sand_rpc >= 1
    assert "/*SAND_SUBAGENT_ROUTE_V1*/" in out
    assert "subagentTypeName" in out
    assert out.count("void 0!==e.runOptions.subagentTypeName") == 1
    assert "!1/*SAND_SUBAGENT_ROUTE_V1*/" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.sand_rpc >= 1
    assert restored == src


def test_317_managed_local_gate_j() -> None:
    src = (
        'try{return(yield o.checkFeatureGate(J))?'
        '{runtime:"managed-local",reason:"eligible"}:'
        '{runtime:"connect",reason:"gate-off"}}catch(e)'
        '{return{runtime:"connect",reason:"gate-check-failed"}}'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.managed_local_route == 1
    assert "/*SAND_MANAGED_LOCAL_ROUTE_V1*/" in out
    assert 'reason:"sand-client"' in out
    assert "checkFeatureGate(J)" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.managed_local_route == 1
    assert restored == src


def test_318_managed_local_gate_ae() -> None:
    src = (
        'try{return(yield o.checkFeatureGate(ae))?'
        '{runtime:"managed-local",reason:"eligible"}:'
        '{runtime:"connect",reason:"gate-off"}}catch(e)'
        '{return{runtime:"connect",reason:"gate-check-failed"}}'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.managed_local_route == 1
    restored, rst = remove_patch_from_content(out)
    assert restored == src


import re
from pathlib import Path

AGENT_HOST_DIST = Path(
    r"D:\GongJu\cursor\resources\app\extensions\cursor-agent-host\dist"
)


def _find_bundle(marker: str) -> "Path | None":
    """按内容定位 bundle：3.17.21=477/478.js，3.18.25=675/61.js，3.19.7=4883/9909.js。"""
    if not AGENT_HOST_DIST.is_dir():
        return None
    for p in sorted(AGENT_HOST_DIST.glob("*.js"), key=lambda x: -x.stat().st_size):
        if marker in p.read_text(encoding="utf-8", errors="replace"):
            return p
    return None


def test_live_478_memory_roundtrip() -> None:
    path = _find_bundle("Agent host interaction registry is closed")
    if path is None:
        print("skip: test_live_478_memory_roundtrip (未找到路由 bundle)")
        return
    print(f"   (live 478-like bundle: {path.name})")
    disk = path.read_text(encoding="utf-8", errors="replace")
    src, _ = remove_patch_from_content(disk)
    assert "/*SAND_" not in src
    is_319 = "isHostedSubagentChild" in src or "direct-meta-subagent-not-supported" in src
    if not is_319:
        assert re.search(r'e\.requestedMode!==\w+\.\w+\.AGENT\?"mode-not-supported":', src)
    assert '"userMessageAction"!==e.actionCase?"action-not-supported":' in src
    out, stats = apply_patch_to_content(src)
    assert stats.managed_local_route >= 1
    assert stats.sand_rpc >= 3
    assert "/*SAND_MANAGED_LOCAL_ROUTE_V1*/" in out
    if is_319:
        assert 'reason:"sand-client"' not in out
        assert "!0/*SAND_MODE_ROUTE_V1*/" in out
    else:
        assert 'reason:"sand-client"' in out
        assert "!1/*SAND_MODE_ROUTE_V1*/" in out
        assert out.count('"mode-not-supported"') == 1
    assert "/*SAND_SUBAGENT_ROUTE_V1*/" in out
    assert "/*SAND_ACTION_ROUTE_V1*/" in out
    if 'e.modelId!==v.w?"model-not-supported":' in src:
        assert stats.model_route == 1
        assert "!1/*SAND_MODEL_ROUTE_V1*/" in out
    again, _ = apply_patch_to_content(disk)
    assert again.count("/*SAND_MODE_ROUTE_V1*/") >= 1
    assert "0!==e.requestedMode" not in again
    assert again.count("/*SAND_SUBAGENT_ROUTE_V1*/") == 1
    assert again.count("/*SAND_ACTION_ROUTE_V1*/") == 1
    assert again.count("/*SAND_SUBAGENT_RETRY_V1*/") == 1
    assert again.count("/*SAND_INTERACTION_ID_V1*/") == 1
    assert "enableAgentRetries:!1}" not in again
    if "isManagedInferenceHttp2Available" in src:
        assert again.count("/*SAND_HTTP2_GATE_V1*/") == 1
        assert "/*SAND_HTTP2_GATE_RB:try{if(!1===" in again
    restored, rst = remove_patch_from_content(out)
    assert rst.managed_local_route >= 1
    assert restored == src


def test_317_local_model_roundtrip() -> None:
    src = (
        "function Doe(e){var t;"
        "if(e.modelId!==Poe.w)throw new Error(`Unsupported managed local model: ${e.modelId}`);"
        "const n=1}"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.local_model == 1
    assert "/*SAND_LOCAL_MODEL_V1*/" in out
    assert "if(!1/*SAND_LOCAL_MODEL_V1*/" in out
    assert "e.modelId!==Poe.w" in out
    restored, rst = remove_patch_from_content(out)
    assert rst.local_model == 1
    assert restored == src


def test_live_477_memory_roundtrip() -> None:
    path = _find_bundle('retryLogTag:"managed_local_agent_retries"')
    if path is None:
        path = _find_bundle("taskToolProps:void 0")
    if path is None:
        print("skip: test_live_477_memory_roundtrip (未找到 agent-host bundle)")
        return
    print(f"   (live 477-like bundle: {path.name})")
    disk = path.read_text(encoding="utf-8", errors="replace")
    src, _ = remove_patch_from_content(disk)
    assert "/*SAND_" not in src
    is_319 = "managed local loop does not build in-process child AgentConfig" in src
    out, stats = apply_patch_to_content(src)
    assert "useClientSideSubagent:!0" in out
    assert "defaultSubagentsRunInBackground:!1" in out
    assert "/*SAND_AGENT_FLAGS_V1*/" in out
    if is_319:
        assert "getTaskToolConfig:async(e,t)=>{" in out
        assert "/*SAND_TASK_TOOL_PROPS_V1*/" in out
        assert "taskToolProps:_sandTtp" not in out
    else:
        assert "taskToolProps:void 0" in src
        assert "taskToolProps:_sandTtp" in out
    assert stats.ctx_window == 2
    assert "maxTokens:_sandCtxWin(n.maxTokens,this.requestedModel)" in out
    assert "/*SAND_BG_SUMMARY_V1*/" in out
    again, _ = apply_patch_to_content(disk)
    assert again.count("/*SAND_AGENT_FLAGS_V1*/") == 1
    assert again.count("/*SAND_TASK_TOOL_PROPS_V1*/") == 1
    assert again.count("/*SAND_CTX_WINDOW_V1*/") == 2
    assert again.count("/*SAND_BG_SUMMARY_V1*/") == 1
    assert again.count("/*SAND_MAX_RETRIES_V1*/") == 1
    assert "defaultSubagentsRunInBackground:!1" in again
    assert "defaultSubagentsRunInBackground:!0" not in again
    if "Unsupported managed local model" in src:
        assert stats.local_model == 1
        assert "if(!1/*SAND_LOCAL_MODEL_V1*/" in out
        assert stats.local_agent == 2
        assert "/*SAND_MODEL_INFO_V1*/" in out
    else:
        assert stats.local_agent >= 1
    restored, _rst = remove_patch_from_content(out)
    assert restored == src


def test_319_managed_local_gate_off_roundtrip() -> None:
    src = (
        'if(!e.managedLocalAvailable)return{runtime:"connect",reason:"managed-local-unavailable"};'
        "const r=e.runtimeCapabilities;"
        'if(!i)return{runtime:"connect",reason:"gate-off"};'
        'const o=g(t),s=v(o,e,r);return void 0!==s?h(s,o):{runtime:"managed-local",reason:"eligible"}'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.managed_local_route >= 1
    assert "/*SAND_MANAGED_LOCAL_ROUTE_V1*/" in out
    assert 'reason:"sand-client"' not in out
    head, _sep, tail = out.partition("/*SAND_MANAGED_LOCAL_ROUTE_V1*/")
    assert "reason:\"gate-off\"" not in head or "SAND_MANAGED_LOCAL_RB:" in out
    assert '{runtime:"managed-local",reason:"eligible"}' in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, rst = remove_patch_from_content(out)
    assert restored == src


def test_319_mode_hosted_iife_roundtrip() -> None:
    src = (
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        "function(e){return e.requestedMode===i.xy.AGENT||e.isHostedSubagentChild&&e.requestedMode===i.xy.UNSPECIFIED}(e)"
        '?e.simulatedUserMessage?"simulated-message-not-supported":T(e,r):"mode-not-supported"'
    )
    out, stats = apply_patch_to_content(src)
    assert stats.sand_rpc >= 2
    assert "!0/*SAND_MODE_ROUTE_V1*/" in out
    assert "/*SAND_ACTION_ROUTE_V1*/" in out
    assert "isHostedSubagentChild" in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, _ = remove_patch_from_content(out)
    assert restored == src


def test_319_direct_meta_and_interaction_const_c() -> None:
    src = (
        "unsupportedRunOptionReason:(l=e.runOptions,void 0!==l.customSystemPrompt?"
        '"custom-system-prompt-not-supported":!0===l.directMetaParentChildSubagent?'
        '"direct-meta-subagent-not-supported":void 0),'
        'if(this.closed)throw new Error("Agent host interaction registry is closed");'
        "const c=null!==(l=null==r?void 0:r.interactionId)&&void 0!==l?l:`${t}:${n.id}`;"
        "subagentModelOverrides:[],enableAgentRetries:null!==(l=null==_?void 0:_.enableAgentRetries)&&void 0!==l&&l,fixedRetryDelayMs:1"
    )
    out, stats = apply_patch_to_content(src)
    assert "/*SAND_SUBAGENT_ROUTE_V1*/" in out
    assert "/*SAND_INTERACTION_ID_V1*/" in out
    assert "/*SAND_SUBAGENT_RETRY_V1*/" in out
    assert "n.id||(n.id=this._sandQid=(this._sandQid||0)+1)/*SAND_INTERACTION_ID_V1*/;const c=" in out
    assert "enableAgentRetries:!0/*SAND_SUBAGENT_RETRY_V1*/" in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, _ = remove_patch_from_content(out)
    assert restored == src


def test_319_createAgentHost_export_ctx_window() -> None:
    from sand_patch import CTX_WINDOW_USAGE_ORIGINAL

    src = (
        "n.d(t,{AGENT_HOST_PRIVATE_INFERENCE_GATE:()=>qe.ZS,createAgentHost:()=>ot,"
        "parsePrivateInferenceConfig:()=>et});"
        + CTX_WINDOW_USAGE_ORIGINAL
    )
    out, stats = apply_patch_to_content(src)
    assert stats.ctx_window == 2
    assert "maxTokens:_sandCtxWin(n.maxTokens,this.requestedModel)" in out
    restored, _ = remove_patch_from_content(out)
    assert restored == src


def test_31825_composite_from_3252da8_still_hits() -> None:
    """3252da8 适配的 3.18.25 形态：当前打补丁器仍必须全部命中，且可还原。

    本机已升级到 3.19.7，没有 675.js/61.js 实装；用该提交锁定的锚点拼一份复合夹具。
    """
    from sand_patch import (
        AGENT_HOST_MODULE_ANCHOR_RE,
        CTX_WINDOW_USAGE_ORIGINAL,
        DOE_TAIL_318_ORIGINAL,
        ROE_DECL_RE,
    )

    export_318 = "n.d(t,{createAgentHost:()=>Rre});"
    assert AGENT_HOST_MODULE_ANCHOR_RE.search(export_318), "3.18.25 单独导出 createAgentHost 必须仍匹配"
    xre = (
        "const xre={enableEmptyResponseRetry:!0,enableGrepBroadGlobGuard:!0,"
        "nalLoopDetection:!0};var cfg={agentType:1,featureFlags:xre,"
        "taskToolProps:void 0};"
    )
    assert ROE_DECL_RE.search(xre), "3.18.25 const xre={enableEmptyResponseRetry:...} 必须仍匹配"

    src = (
        export_318
        + "function Rre(){}"
        + xre
        + "function Doe(e){return Object.assign({},g,{maxSteps:128"
        + DOE_TAIL_318_ORIGINAL
        + "agentTokenLimit:e}"
        + CTX_WINDOW_USAGE_ORIGINAL
        + 'try{return(yield o.checkFeatureGate(ae))?'
        '{runtime:"managed-local",reason:"eligible"}:'
        '{runtime:"connect",reason:"gate-off"}}catch(e)'
        '{return{runtime:"connect",reason:"gate-check-failed"}}'
        "try{if(!1===(null===(n=t.isManagedInferenceHttp2Available)||void 0===n?"
        'void 0:n.call(t)))return"managed-local-http2-unavailable"}'
        'catch(e){return"managed-local-http2-unavailable"}'
        '"userMessageAction"!==e.actionCase?"action-not-supported":'
        'e.requestedMode!==w.xyI.AGENT?"mode-not-supported":void 0;'
        "void 0!==e.runOptions.subagentTypeName"
        "||void 0!==e.runOptions.parentAgentToolCallId"
        "||!0===e.runOptions.directMetaParentChildSubagent;"
        's.header.set("x-cursor-client-type",null!==(i=null==r?void 0:r.clientType)'
        '&&void 0!==i?i:"cli");'
        "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}catch(e){t=!1}"
        "p=await Promise.resolve(n.cursor.checkFeatureGate(xo)).catch(()=>!1);"
        'clientIdentity:{clientType:"ide"};'
        "subagentModelOverrides:[],enableAgentRetries:null!==(u=null==v?void 0:v.enableAgentRetries)"
        "&&void 0!==u&&u,fixedRetryDelayMs:1;"
        'if(this.closed)throw new Error("Agent host interaction registry is closed");'
        "const m=`${t}:${n.id}`;"
        "function gre(e){return t=>{return n=this,o=void 0,s=function*(){"
    )
    out, stats = apply_patch_to_content(src)
    assert stats.managed_local_route == 1
    assert stats.local_runtime_load == 1
    assert stats.move_exec == 1
    assert stats.agent_host_identity == 1
    assert stats.ctx_window == 2
    assert stats.local_agent >= 1
    assert stats.sand_rpc >= 3
    assert 'reason:"sand-client"' in out
    assert "/*SAND_HTTP2_GATE_V1*/" in out
    assert "!1/*SAND_MODE_ROUTE_V1*/" in out
    assert "/*SAND_SUBAGENT_ROUTE_V1*/" in out
    assert "/*SAND_ACTION_ROUTE_V1*/" in out
    assert "taskToolProps:_sandTtp" in out
    assert "useClientSideSubagent:!0" in out
    assert "/*SAND_BG_SUMMARY_V1*/" in out
    assert "maxTokens:_sandCtxWin(n.maxTokens,this.requestedModel)" in out
    assert "enableAgentRetries:!0/*SAND_SUBAGENT_RETRY_V1*/" in out
    assert "n.id||(n.id=this._sandQid=(this._sandQid||0)+1)/*SAND_INTERACTION_ID_V1*/;const m=" in out
    assert "function gre(e){" in out
    again, _ = apply_patch_to_content(out)
    assert again == out
    restored, _ = remove_patch_from_content(out)
    assert restored == src


def test_live_3197_key_markers() -> None:
    """本机 3.19.7：9909.js / 4883.js / agent-host main.js 干跑必须打上新闸门。"""
    import json

    app = Path(r"D:\GongJu\cursor\resources\app")
    product = app / "product.json"
    if not product.is_file():
        print("skip: test_live_3197_key_markers (no Cursor install)")
        return
    version = json.loads(product.read_text(encoding="utf-8")).get("version", "")
    if not str(version).startswith("3.19"):
        print(f"skip: test_live_3197_key_markers (Cursor {version}, want 3.19.x)")
        return

    files = {
        app / "extensions" / "cursor-agent-host" / "dist" / "9909.js": (
            "/*SAND_MANAGED_LOCAL_ROUTE_V1*/",
            "/*SAND_MODE_ROUTE_V1*/",
            "/*SAND_SUBAGENT_ROUTE_V1*/",
            "/*SAND_HTTP2_GATE_V1*/",
            "/*SAND_ACTION_ROUTE_V1*/",
            "/*SAND_INTERACTION_ID_V1*/",
            "/*SAND_SUBAGENT_RETRY_V1*/",
        ),
        app / "extensions" / "cursor-agent-host" / "dist" / "4883.js": (
            "/*SAND_AGENT_FLAGS_V1*/",
            "/*SAND_TASK_TOOL_PROPS_V1*/",
            "/*SAND_CTX_WINDOW_V1*/",
            "/*SAND_BG_SUMMARY_V1*/",
            "/*SAND_MAX_RETRIES_V1*/",
            "/*SAND_DIRECT_INFERENCE_STREAM_V1*/",
            "/*SAND_RECONNECT_STREAM_V1*/",
        ),
        app / "extensions" / "cursor-agent-host" / "dist" / "main.js": (
            "/*SAND_LOCAL_RUNTIME_LOAD_V1*/",
            "/*SAND_MOVE_EXEC_V1*/",
            "/*SAND_AGENT_HOST_IDENTITY_V1*/",
        ),
    }
    for path, markers in files.items():
        if not path.is_file():
            raise AssertionError(f"3.19.7 缺少 {path.name}")
        src, _ = remove_patch_from_content(path.read_text(encoding="utf-8", errors="replace"))
        out, _stats = apply_patch_to_content(src)
        restored, _ = remove_patch_from_content(out)
        assert restored == src, path.name
        missing = [m for m in markers if m not in out]
        assert not missing, f"{path.name} 缺 marker: {missing}"
        if path.name == "9909.js":
            assert 'reason:"sand-client"' not in out
            assert "!0/*SAND_MODE_ROUTE_V1*/" in out
        if path.name == "4883.js":
            assert "getTaskToolConfig:async(e,t)=>{" in out
            assert "taskToolProps:_sandTtp" not in out
            assert "new J(e,n,void 0,void 0).getSession()" in out
            assert "new o.Ycw(s.getExecutor(e))" in out
            assert "resolvedModelMetadata:{promptModelInfo:oe(a,mid)}" in out
            assert "resolvedModelMetadata:void 0" not in out
            assert "e.runInference" not in out.split("/*SAND_DIRECT_INFERENCE_STREAM_V1*/", 1)[1][:400]
            assert 'reconnectEndpoint:"InferenceService.Stream"' in out
            assert 'reconnectEndpoint:"InferenceService.RunInference"' not in out


def test_dns_node_roundtrip() -> None:
    from dns_fix import SAND_DNS_FIX_MARKER, apply_dns_node_patch, remove_dns_node_patch

    src = 'require("electron");'
    out, pst = apply_dns_node_patch(src)
    assert pst == 1
    assert out.startswith(SAND_DNS_FIX_MARKER)
    restored, rst = remove_dns_node_patch(out)
    assert rst == 1
    assert restored == src


def main() -> int:
    tests = [
        test_orphan_live,
        test_original_g_fallback,
        test_get_type_and_version,
        test_main_object,
        test_idempotent,
        test_agent_host_identity_roundtrip,
        test_agent_host_enablement_roundtrip,
        test_direct_stream_3189_anchor,
        test_direct_stream_skipped_on_317,
        test_direct_stream_3197_ve_anchor,
        test_317_local_loop_roundtrip,
        test_318_local_runtime_roundtrip,
        test_317_move_exec_roundtrip,
        test_478_namespace_roundtrip,
        test_317_model_route_roundtrip,
        test_478_mode_route_roundtrip,
        test_478_mode_route_legacy_form_migrates,
        test_318_http2_gate_roundtrip,
        test_477_local_agent_config_roundtrip,
        test_477_ctx_window_roundtrip,
        test_retry_resilience_roundtrip,
        test_server_mode_hybrid_identity_and_unlocks,
        test_478_subagent_run_options_roundtrip,
        test_317_managed_local_gate_j,
        test_318_managed_local_gate_ae,
        test_319_managed_local_gate_off_roundtrip,
        test_319_mode_hosted_iife_roundtrip,
        test_319_direct_meta_and_interaction_const_c,
        test_319_createAgentHost_export_ctx_window,
        test_31825_composite_from_3252da8_still_hits,
        test_live_3197_key_markers,
        test_live_478_memory_roundtrip,
        test_317_local_model_roundtrip,
        test_live_477_memory_roundtrip,
        test_dns_node_roundtrip,
    ]
    for test in tests:
        test()
        print("ok:", test.__name__)
    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
