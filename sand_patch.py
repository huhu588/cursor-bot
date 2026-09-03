"""交互式运行：
    python "Sand客户端模式安装工具.py"

命令行运行：
    python "Sand客户端模式安装工具.py" install
    python "Sand客户端模式安装工具.py" uninstall
    python "Sand客户端模式安装工具.py" set-path <Cursor路径|auto>
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple, Union

from dns_fix import (
    DNS_NODE_TARGETS,
    SAND_DNS_FIX_MARKER,
    apply_dns_node_patch,
    diagnose_dns,
    hosts_block_installed,
    install_hosts,
    remove_dns_node_patch,
    remove_hosts,
)


TOOL_VERSION = "2.2.9"
CONFIG_VERSION = 1

SAND_CLIENT_MARKER = "/*SAND_CLIENT_MODE_V1*/"
SAND_CLIENT_EXISTING_MARKER = "/*SAND_CLIENT_EXISTING_V1*/"
SAND_ELIGIBILITY_MARKER = "/*SAND_ELIGIBILITY_MODE_V1*/"
SAND_MODEL_UNLOCK_MARKER = "/*SAND_MODEL_UNLOCK_V1*/"
SAND_MEM_PRO_MARKER = "/*SAND_MEM_PRO_V1*/"
SAND_MAXMODE_MARKER = "/*SAND_MAXMODE_V1*/"
SAND_GLASSFIX_MARKER = "/*SAND_GLASSFIX_V1*/"
SAND_HDRFIX_MARKER = "/*SAND_HDRFIX_V1*/"
SAND_HDRFIX_RB_PREFIX = "/*SAND_HDRFIX_RB:"
SAND_HDRFIX_RB_SUFFIX = "*/"
SAND_VERFIX_MARKER = "/*SAND_VERFIX_V1*/"
SAND_VERFIX_RB_PREFIX = "/*SAND_VERFIX_RB:"
SAND_VERFIX_RB_SUFFIX = "*/"
SAND_NSFIX_MARKER = "/*SAND_NSFIX_V1*/"
SAND_MEMBERSHIP_MARKER = "/*SAND_MEMBERSHIP_SPOOF_V1*/"
SAND_MANAGED_LOCAL_ROUTE_MARKER = "/*SAND_MANAGED_LOCAL_ROUTE_V1*/"
SAND_MANAGED_LOCAL_RB_PREFIX = "/*SAND_MANAGED_LOCAL_RB:"
SAND_MANAGED_LOCAL_RB_SUFFIX = "*/"
SAND_MODEL_ROUTE_MARKER = "/*SAND_MODEL_ROUTE_V1*/"
SAND_MODEL_ROUTE_RB_PREFIX = "/*SAND_MODEL_ROUTE_RB:"
SAND_MODEL_ROUTE_RB_SUFFIX = "*/"
SAND_LOCAL_MODEL_MARKER = "/*SAND_LOCAL_MODEL_V1*/"
SAND_LOCAL_MODEL_RB_PREFIX = "/*SAND_LOCAL_MODEL_RB:"
SAND_LOCAL_MODEL_RB_SUFFIX = "*/"
SAND_DIRECT_STREAM_MARKER = "/*SAND_DIRECT_INFERENCE_STREAM_V1*/"
SAND_AGENT_HOST_ENABLEMENT_MARKER = "/*SAND_AGENT_HOST_ENABLEMENT_V1*/"
SAND_LOCAL_RUNTIME_LOAD_MARKER = "/*SAND_LOCAL_RUNTIME_LOAD_V1*/"
SAND_LOCAL_RB_PREFIX = "/*SAND_LOCAL_RB:"
SAND_LOCAL_RB_SUFFIX = "*/"
SAND_MOVE_EXEC_MARKER = "/*SAND_MOVE_EXEC_V1*/"
SAND_MOVE_EXEC_RB_PREFIX = "/*SAND_MOVE_EXEC_RB:"
SAND_MOVE_EXEC_RB_SUFFIX = "*/"
SAND_AGENT_HOST_IDENTITY_MARKER = "/*SAND_AGENT_HOST_IDENTITY_V1*/"
SAND_FEATURE_FLAG_MARKER = "/*SAND_FEATURE_FLAG_V1*/"
SAND_FF_RB_PREFIX = "/*SAND_FF_RB:"
SAND_FF_RB_SUFFIX = "*/"
SAND_AGENT_FLAGS_MARKER = "/*SAND_AGENT_FLAGS_V1*/"
SAND_EXEC_BRIDGE_MARKER = "/*SAND_EXEC_BRIDGE_V1*/"
SAND_BR_RESOURCE_BRIDGE_MARKER = "/*SAND_BR_RESOURCE_BRIDGE_V1*/"
SAND_TASK_TOOL_PROPS_MARKER = "/*SAND_TASK_TOOL_PROPS_V1*/"
SAND_SELF_SUMMARY_MARKER = "/*SAND_SELF_SUMMARY_V1*/"
SAND_SUBAGENT_ROUTE_MARKER = "/*SAND_SUBAGENT_ROUTE_V1*/"
SAND_SUBAGENT_ROUTE_RB_PREFIX = "/*SAND_SUBAGENT_ROUTE_RB:"
SAND_SUBAGENT_ROUTE_RB_SUFFIX = "*/"
SAND_MODE_ROUTE_MARKER = "/*SAND_MODE_ROUTE_V1*/"
SAND_MODE_ROUTE_RB_PREFIX = "/*SAND_MODE_ROUTE_RB:"
SAND_MODE_ROUTE_RB_SUFFIX = "*/"
SAND_CTX_WINDOW_MARKER = "/*SAND_CTX_WINDOW_V1*/"
SAND_CTX_WINDOW_END_MARKER = "/*SAND_CTX_WINDOW_END_V1*/"
SAND_ACTION_ROUTE_MARKER = "/*SAND_ACTION_ROUTE_V1*/"
SAND_ACTION_ROUTE_RB_PREFIX = "/*SAND_ACTION_ROUTE_RB:"
SAND_ACTION_ROUTE_RB_SUFFIX = "*/"
SAND_BG_SUMMARY_MARKER = "/*SAND_BG_SUMMARY_V1*/"
SAND_MODEL_INFO_MARKER = "/*SAND_MODEL_INFO_V1*/"
SAND_MODEL_INFO_END_MARKER = "/*SAND_MODEL_INFO_END_V1*/"
SAND_SUBAGENT_RETRY_MARKER = "/*SAND_SUBAGENT_RETRY_V1*/"
SAND_MAX_RETRIES_MARKER = "/*SAND_MAX_RETRIES_V1*/"
SAND_INTERACTION_ID_MARKER = "/*SAND_INTERACTION_ID_V1*/"

# 网络抖动韧性（2.2.6，3.17.21 日志实测）：
# - 478 子代理执行器给子 turn 写死 enableAgentRetries:!1 → 一次 socket hang up 子代理就死，
#   父 turn 续跑时把它从零重启，看起来像「整个任务重跑」。改为 !0，子 turn 也走
#   turn-runner 的重试 + checkpoint resumeAction 续跑。
# - 477 Uoe 没传 maxRetries，aoe.classify 默认 3；代理频繁切节点时 3 次很快耗尽，整个
#   turn 报错需手动 Resume。提到 8（退避最长 60s，重试用 resumeAction 从最新 checkpoint 续）。
SIMPLE_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    (
        "subagentModelOverrides:[],enableAgentRetries:!1}",
        "subagentModelOverrides:[],enableAgentRetries:!0" + SAND_SUBAGENT_RETRY_MARKER + "}",
    ),
    (
        'retryLogTag:"managed_local_agent_retries",reconnectEndpoint:"InferenceService.Stream"',
        'retryLogTag:"managed_local_agent_retries",maxRetries:8'
        + SAND_MAX_RETRIES_MARKER
        + ',reconnectEndpoint:"InferenceService.Stream"',
    ),
    # 3.18.25：会话工厂改走 InferenceService.RunInference（不再写 Stream 字面量）。
    (
        'retryLogTag:"managed_local_agent_retries",reconnectEndpoint:"InferenceService.RunInference"',
        'retryLogTag:"managed_local_agent_retries",maxRetries:8'
        + SAND_MAX_RETRIES_MARKER
        + ',reconnectEndpoint:"InferenceService.RunInference"',
    ),
    # 478 交互注册表（2.2.7，3.17.21 日志实测 "Unexpected response for create plan query:
    # askQuestionInteractionResponse"）：key 是 `${turnId}:${query.id}`，但所有 InteractionQuery
    # 构造时都没设 id（uint32 默认 0），同一 turn 里 AskQuestion 与 CreatePlan 撞成同一个 key，
    # CreatePlan 拿到 AskQuestion 的（缓存）回包直接抛错。这里在算 key 前给无 id 的 query 分配
    # 自增 id；pending 里存的克隆和发给 renderer 的都是同一对象，respond 的 id 校验自然匹配。
    (
        'if(this.closed)throw new Error("Agent host interaction registry is closed");const m=',
        'if(this.closed)throw new Error("Agent host interaction registry is closed");'
        "n.id||(n.id=this._sandQid=(this._sandQid||0)+1)"
        + SAND_INTERACTION_ID_MARKER
        + ";const m=",
    ),
)

# 478.js 动作闸门：`"userMessageAction"!==e.actionCase?"action-not-supported"` 把 resume /
# 订阅通知 / 执行计划 / AskQuestion 回灌 / cancel 等全部踢到 connect（sand 下必失败）。
# 477 managed-local 的 ooe.actionHandlers 其实注册了下面全部 12 种 case，闸门过窄。
MANAGED_LOCAL_ACTION_CASES: Tuple[str, ...] = (
    "userMessageAction",
    "subscriptionNotificationAction",
    "goalContinuationAction",
    "resumeAction",
    "summarizeAction",
    "shellCommandAction",
    "cancelAction",
    "executePlanAction",
    "asyncAskQuestionCompletionAction",
    "backgroundTaskCompletionAction",
    "backgroundShellAction",
    "backgroundSubagentAction",
)
# 3.18.x 新增闸门：isManagedInferenceHttp2Available() 返回 false 或抛异常时改走 connect。
# 它排在所有其它闸门之前，而 connect 对 sand 身份必定被拒（Sand traffic is not supported），
# 所以「优雅回落」在这里等于必然失败——代理不支持 HTTP/2 时会静默毁掉整个会话。
# 整块 try/catch 折成注释（RB 保留原文），让判定继续往下走。
SAND_HTTP2_GATE_MARKER = "/*SAND_HTTP2_GATE_V1*/"
SAND_HTTP2_GATE_RB_PREFIX = "/*SAND_HTTP2_GATE_RB:"
SAND_HTTP2_GATE_RB_SUFFIX = "*/"
HTTP2_GATE_RE = re.compile(
    r'try\{if\(!1===\(.{0,200}?isManagedInferenceHttp2Available.{0,200}?\)\)'
    r'return"managed-local-http2-unavailable"\}'
    r'catch\(\w+\)\{return"managed-local-http2-unavailable"\}'
)
HTTP2_GATE_RB_RE = re.compile(
    re.escape(SAND_HTTP2_GATE_MARKER)
    + re.escape(SAND_HTTP2_GATE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_HTTP2_GATE_RB_SUFFIX)
)

ACTION_GATE_ORIGINAL = '"userMessageAction"!==e.actionCase?"action-not-supported":'
ACTION_GATE_PATCHED = (
    "!["
    + ",".join(f'"{case}"' for case in MANAGED_LOCAL_ACTION_CASES)
    + "].includes(e.actionCase)"
    + SAND_ACTION_ROUTE_MARKER
    + SAND_ACTION_ROUTE_RB_PREFIX
    + '"userMessageAction"!==e.actionCase'
    + SAND_ACTION_ROUTE_RB_SUFFIX
    + '?"action-not-supported":'
)
ACTION_ROUTE_RB_RE = re.compile(
    r"!\[[^\]]*\]\.includes\(e\.actionCase\)"
    + re.escape(SAND_ACTION_ROUTE_MARKER)
    + re.escape(SAND_ACTION_ROUTE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_ACTION_ROUTE_RB_SUFFIX)
    + r'\?"action-not-supported":'
)

# 477.js Doe()：managed-local 配置里没有 backgroundSummarizationProps，后台摘要永不按阈值
# 触发，只剩「超窗口 + min(25%,50K)」的强制摘要。数值对齐 cursor-local-agent-runtime 的
# xHt（used ≥90% 开始后台摘要，≥95% 持久化）。
DOE_TAIL_ORIGINAL = ",nonFileRules:[],enableTerminalFiles:!0})}"
_SAND_BG_SUMMARY_PROPS = (
    "backgroundSummarizationProps:{"
    "unusedTokensThresholdToStartBackgroundSummarization:1e4,"
    "unusedPercentTokensThresholdToStartBackgroundSummarization:.1,"
    "unusedTokensThresholdToPersistBackgroundSummarization:5e3,"
    "unusedPercentTokensThresholdToPersistBackgroundSummarization:.05}"
)
DOE_TAIL_PATCHED = (
    ",nonFileRules:[],enableTerminalFiles:!0,"
    + _SAND_BG_SUMMARY_PROPS
    + SAND_BG_SUMMARY_MARKER
    + "})}"
)
# 3.18.25 675.js：Doe 尾部后面还跟 agentTokenLimit，不是函数结束的 `})}`.
DOE_TAIL_318_ORIGINAL = ",nonFileRules:[],enableTerminalFiles:!0}),"
DOE_TAIL_318_PATCHED = (
    ",nonFileRules:[],enableTerminalFiles:!0,"
    + _SAND_BG_SUMMARY_PROPS
    + SAND_BG_SUMMARY_MARKER
    + "}),"
)

# 仅 3.17.x 需要：那时 Doe() 把 modelInfo 写死为 claude-sonnet-4-6 +
# {anthropic,isClaude4X,isSonnet4}，Opus 5 / Fable 5.x 丢掉专用 prompt 段，grok/gemini
# 丢 vendor。这里按 modelId 计算 Claude/Grok/Gemini 系 flags；GPT/Codex 相关 flag 保持
# 关闭（打开会切到 ApplyPatch / GPT 专用协议，在 InferenceService/Stream 下未验证）。
# 3.18.x 起 modelInfo 改由服务端 resolvedModelMetadata.promptModelInfo 下发，锚点不存在，
# 本补丁自动跳过（原生行为已正确）。
MODEL_INFO_ORIGINAL = '{vendor:"anthropic",isClaude4X:!0,isSonnet4:!0}'
_SAND_MODEL_INFO_FN = (
    'function(m){var i=String(m||"").toLowerCase().replace(/\\./g,"-"),'
    'c=i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable")||i.includes("haiku"),'
    'g=i.includes("grok"),n=i.includes("gemini"),'
    'p=e.requestedModel&&e.requestedModel.parameters?e.requestedModel.parameters.find(function(e){return"effort"===e.id}):void 0;'
    'return{vendor:g?"xai":n?"gemini":"anthropic",modelName:String(m||"claude-sonnet-4-6"),'
    "isClaude4X:c||!(g||n),"
    'isSonnet4:i.includes("sonnet-4"),'
    'isSonnet45:i.includes("sonnet-4-5"),'
    'isOpus45:i.includes("opus-4-5")||i.includes("4-5-opus"),'
    'isOpus46:i.includes("opus-4-6")||i.includes("4-6-opus"),'
    'isOpus48:i.includes("opus-4-8")||i.includes("4-8-opus"),'
    'isOpus5:i.includes("opus-5")||i.includes("5-opus"),'
    'isFable5:i.includes("fable-5"),'
    'isGemini3:n&&i.includes("gemini-3"),'
    "isGrok45ProductPrompt:g,"
    "reasoningEffort:p?String(p.value):void 0}}"
)
MODEL_INFO_PATCHED = (
    "("
    + SAND_MODEL_INFO_MARKER
    + _SAND_MODEL_INFO_FN
    + "(e.modelId)"
    + SAND_MODEL_INFO_END_MARKER
    + ")"
)
MODEL_INFO_PATCHED_RE = re.compile(
    re.escape("(" + SAND_MODEL_INFO_MARKER)
    + r".*?"
    + re.escape(SAND_MODEL_INFO_END_MARKER + ")")
)

# 上下文窗口分母修正（2.2.3，3.17.21 实测）：
# UI「Context Usage」的分母 = agent-host tokenDetails.maxTokens = InferenceService/Stream
# 流里 extended_usage.max_tokens。sand 走的这个端点对 claude-fable-5-1 无论
# maxMode / context=1m 都固定回 300000（模型目录里 contextTokenLimitForMaxMode 是 1000000，
# 且 330K 的请求能正常完成并计费，说明模型确实按 1M 跑），只是元数据写死。
# 这里按 requestedModel.parameters 里用户实际选的 context=1m/300k 换算窗口，
# 没有 context 参数时保持服务端值。压缩/摘要阈值同样基于 maxTokens，会一并对齐。
CTX_WINDOW_USAGE_ORIGINAL = (
    "t.resolveExtendedUsage({inputTokens:n.inputTokens,outputTokens:n.outputTokens,"
    "cacheReadTokens:n.cacheReadTokens,cacheWriteTokens:n.cacheWriteTokens,"
    "maxTokens:n.maxTokens})"
)
CTX_WINDOW_USAGE_PATCHED = (
    "t.resolveExtendedUsage({inputTokens:n.inputTokens,outputTokens:n.outputTokens,"
    "cacheReadTokens:n.cacheReadTokens,cacheWriteTokens:n.cacheWriteTokens,"
    "maxTokens:_sandCtxWin(n.maxTokens,this.requestedModel)"
    + SAND_CTX_WINDOW_MARKER
    + "})"
)
_SAND_CTX_WIN_FN = (
    "function(e,t){try{var n=t&&t.parameters?t.parameters.find(function(e){"
    'return"context"===e.id}):void 0;if(!n)return e;'
    'var o=/^(\\d+(?:\\.\\d+)?)([km])$/i.exec(String(n.value||"").trim());if(!o)return e;'
    'var r=Math.round(parseFloat(o[1])*("m"===o[2].toLowerCase()?1e6:1e3));'
    "return r>0?r:e}catch(n){return e}}"
)
CTX_WINDOW_DECL = (
    ";var _sandCtxWin="
    + SAND_CTX_WINDOW_MARKER
    + _SAND_CTX_WIN_FN
    + SAND_CTX_WINDOW_END_MARKER
    + ";"
)
CTX_WINDOW_DECL_RE = re.compile(
    re.escape(";var _sandCtxWin=" + SAND_CTX_WINDOW_MARKER)
    + r".*?"
    + re.escape(SAND_CTX_WINDOW_END_MARKER + ";")
)

# sand-rpc-lite（2.2.1）：在保留 managed-local + InferenceService/Stream（Bot 额度）前提下，
# 向 477.js 注入 taskToolProps 工厂对象，使 TASK 工具能注册；并把 direct-stream 的
# supportsSelfSummary 从 !1 改为 !0。完整 AgentService/Run ↔ InferenceStream 的双向
# proto 重编码见 sand_rpc/ 模块（Python 参考实现 + 测试），后续可挂本地 bridge。
AGENT_HOST_MODULE_ANCHOR = "n.d(t,{createAgentHost:()=>Loe});"
# 3.17.21 导出 Loe；3.18.25 导出 Rre。按 webpack 导出语句匹配，避免写死混淆名。
AGENT_HOST_MODULE_ANCHOR_RE = re.compile(
    r"n\.d\(t,\{createAgentHost:\(\)=>[A-Za-z_$][A-Za-z0-9_$]*\}\);"
)
_DOE_PROVIDER_OPTIONS_SIG = (
    "function Doe(e){return void 0===e?{}:{providerOptions:{cursor:{modelName:e}}}}"
)
TASK_TOOL_PROPS_VOID = "taskToolProps:void 0"
TASK_TOOL_PROPS_REF = "taskToolProps:_sandTtp"
_SAND_TTP_OBJECT = (
    "{getTaskToolConfig:async(e,t)=>{"
    "try{return{agentConfig:Doe({modelId:e}),promptSession:void 0,summarizationHandler:void 0}}"
    "catch(n){return{agentConfig:void 0,promptSession:void 0,summarizationHandler:void 0}}},"
    "normalizeCustomSubagents:e=>e||[],"
    "parentRequestedModelName:void 0,parentModelParameters:void 0,parentMaxMode:!1,"
    "isModelBlocked:()=>!1,isModelValid:()=>!0,requiresMaxMode:()=>!1,"
    "forceModelId:void 0,compareModelCosts:()=>0,subagentModelForcePolicy:\"none\","
    "requireServerSideSubagent:!1,enableShellSubagent:!0,enableBrowserSubagent:!1,"
    "enableGrindSwarmSubagent:!1,subagentInheritGuidance:!0,"
    "subagentModels:{modelsBySlug:new Map},"
    "subagentCredentials:void 0,attachedMediaUrlProvider:void 0,"
    "subagentModelOverrides:void 0}"
)
TASK_TOOL_PROPS_DECL = (
    ";var _sandTtp=" + SAND_TASK_TOOL_PROPS_MARKER + _SAND_TTP_OBJECT + ";"
)
TASK_TOOL_PROPS_DECL_PREFIX = ";var _sandTtp=" + SAND_TASK_TOOL_PROPS_MARKER
# ---- 背景（3.17.21 实测）----
# managed-local 477.js 里 taskToolProps 唯一赋值为 void 0 → TASK 不注册。
# full-loop（改走 connect + AgentService/Run）会 Connection Error：Sand 身份只在
# InferenceService/Stream 被接受。2.2.0 注入 taskToolProps；2.2.1 补上 Roe 运行期
# flags（useClientSideSubagent 等），并绕过 478.js hasUnsupportedRunOptions 里对
# subagentTypeName / parentAgentToolCallId 的排除，否则子代理 turn 会被改道
# connect → AgentService/Run → Sand Connection Error。
# getTaskToolConfig 在 prepare 就会以 (modelId, subagentType) 调用，必须返回
# {agentConfig, promptSession, summarizationHandler}，不能再透传 o||[]。
# 执行走 Roe.useClientSideSubagent + 478 路由绕过（本机再开一轮 Stream）；
# 不要开 glassMetaParentAgent / enableCloudAsyncSubagents。
# full-loop 已在 2.1.3 移除。
_LEGACY_FULL_LOOP_CONFIG_KEY = "fullLoop"


def _read_config_dict_relaxed() -> Dict[str, object]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _drop_legacy_full_loop_key() -> None:
    """清掉 2.1.2 遗留的 fullLoop 配置项，防止旧配置影响后续安装判定。"""
    cfg = _read_config_dict_relaxed()
    if _LEGACY_FULL_LOOP_CONFIG_KEY not in cfg:
        return
    cfg.pop(_LEGACY_FULL_LOOP_CONFIG_KEY, None)
    cfg["version"] = CONFIG_VERSION
    cfg.setdefault("cursorInstallRoot", "")
    cfg.setdefault("lastVerifiedVersion", "")
    cfg["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(_config_path(), cfg)

# Statsig 客户端开关：默认 false 会关掉 Grok Bot 动态工具、并行子代理 / Task+Todo 等原生能力。
# 安装时改为 default:!0，并把原片段写入 RB 供 uninstall 精确还原。
SAND_FEATURE_FLAGS_DEFAULT_ON: Tuple[str, ...] = (
    "grok_bot_dynamic_tools",
    "parallel_agent_workflow",
    "fix_grok_subagent_await",
    "enable_await_for_subagents",
    "cursor_agent_host",
    "cursor_agent_host_move_exec",
    "agent_host_local_loop",
)

# 运行期 featureFlags 对象（3.17.21 的 const Roe={...} / 3.18.25 的 const xre={...}）。
# 2.0.9 只注 flags、没注 taskToolProps → TASK 不注册，2.1.0 把注入撤掉。
# 2.2.1 两者一起开：if(z) 让 TASK 进清单；useClientSideSubagent 让执行走本机
# managed-local / InferenceService/Stream（Bot 额度），而不是 AgentService/Run。
# 不打开 enableCloudAsyncSubagents，避免子代理被送上云 VM。
SAND_AGENT_RUNTIME_FLAGS: Tuple[Tuple[str, str], ...] = (
    ("useClientSideSubagent", "!0"),
    ("enableNestedSubagents", "!0"),
    ("enableExploreSubagent", "!0"),
    ("enableAwaitForSubagents", "!0"),
    ("enableDebugSubagent", "!0"),
    ("enableCiInvestigatorSubagent", "!0"),
    ("enablePastConversationExplorerSubagent", "!0"),
    ("allowResumeSelfFork", "!0"),
    # 前台同步：Task 阻塞到子代理跑完并把结果直接回父会话。后台模式需要 Await
    # 工具（依赖 longRunningJobs），而 Roe 没开，模型只能 resume，体验差且易错。
    ("defaultSubagentsRunInBackground", "!1"),
    ("subagentSupportInterrupt", "!0"),
    # Multitask 模式：Task 工具带「始终后台并行」约束文案；Multitask 提示词里模型会自己
    # 给每个 Task 传 run_in_background，不需要改全局默认值。
    ("enableMultitaskMode", "!0"),
    # Ask 模式：sandbox 可用时 Shell 进只读沙箱（无 sandbox 时仅靠 reminder 约束，与原生一致）。
    ("enableReadonlyShell", "!0"),
)
# 该对象的变量名每次打包都会变（3.17.21 是 Roe，3.18.25 是 xre），但字段内容稳定。
# 按内容签名定位，再用捕获到的名字确认 featureFlags:<名> 确实引用了它。
ROE_DECL_RE = re.compile(
    r"const ([A-Za-z_$][A-Za-z0-9_$]*)=\{enableEmptyResponseRetry:[^{}]*\}"
)

# exec-bridge（移植自 SandClientMode 1.3.0，本机 3.17.21 锚点已实测命中）：
# managed-local 下工具执行器按 Symbol 从 resources 取；agent-exec 与 agent-host
# 的注册表不完全重叠时 get() 返回 undefined，工具调用直接失败且无任何日志。
# 这里给两处 get 加「回落到 baseResources + 打印 miss」的兜底，行为向后兼容：
# 命中时与原逻辑完全一致，只有原本要返回 undefined 的路径才多试一次。
EXEC_BRIDGE_GET_ORIGINAL = "get:e=>o.resources.get(e),entries:()=>o.resources.entries()"
EXEC_BRIDGE_GET_PATCHED = (
    "get:e=>{const _sand_t=o.resources.get(e);if(void 0!==_sand_t)return _sand_t;"
    + SAND_EXEC_BRIDGE_MARKER
    + "try{const _sand_b=o.baseResources.get(e);if(void 0!==_sand_b)return _sand_b;"
    'console.error("[sand-exec] resource miss",typeof e==="symbol"?e.description||"symbol":String(e))}'
    "catch(_sand_e){}return void 0},entries:()=>o.resources.entries()"
)
BR_RESOURCE_GET_ORIGINAL = "get(e){return this.provider.get(e)}"
BR_RESOURCE_GET_PATCHED = (
    "get(e){const _sand_t=this.provider.get(e);if(void 0!==_sand_t)return _sand_t;"
    + SAND_BR_RESOURCE_BRIDGE_MARKER
    + 'try{console.error("[sand-exec] Br.get miss",typeof e==="symbol"?e.description||"symbol":String(e))}'
    "catch(_sand_e){}return void 0}"
)

# 对齐 Grok Bot 0.18 源码 + 已验证可工作的 sand_stream_installer(4).py：
#   x-cursor-client-type: "sand"
#   x-sand-box-namespace: "prod"
#   不要改 x-cursor-client-version（Cursor 3.x 聊天仍要带自己的版本号）。
# 高级模型（Claude Opus 5）走 InferenceService/Stream（3.18.25 为 RunInference）。
# 3.18.9：workbench hre 注入改道；3.18.25：675.js gre 注入改道；
# 3.17.21：打开 agent_host_local_loop 加载 477.js，
# 并绕过 478.js 路由白名单 + 477.js Doe()「Unsupported managed local model」，
# 否则 UI 会 Connection Error（根本走不到 InferenceService）。
PATCH_CLIENT_TYPE = "sand"
SAND_CLIENT_VERSION = "0.18.0"
SAND_BOX_NAMESPACE = "prod"
STREAM_CURSOR_VERSION = "3.18.25"

# 会员伪装 + 模型列表解锁注入：拦截 renderer 里的 fetch，
#   - 会员/用量/Stripe 类响应把 membershipType 等改成 pro（注意：full_stripe_profile 是 text/plain + 数组！）
#   - AvailableModels 响应把每个模型设 defaultOn:true
# 用 .text()+JSON.parse 兜住 text/plain；数组逐元素改。全程 try/catch，出错原样返回。语法已 node --check 校验。
SAND_MEMBERSHIP_SNIPPET = (
    SAND_MEMBERSHIP_MARKER
    + '(function(){try{var G=(typeof globalThis!=="undefined")?globalThis:(typeof self!=="undefined"?self:this);'
    + 'if(!G||G.__sandMemPatch)return;G.__sandMemPatch=1;'
    + 'var MEM={membershipType:"enterprise",membership_type:"enterprise",isTeamMember:true,teamId:28945905,teamMembershipType:"SELF_SERVE",subscriptionStatus:"active",subscription_status:"active"};'
    + 'function dm(a,b){if(a===null||typeof a!=="object")return a;for(var k in b){var v=b[k];'
    + 'if(v&&typeof v==="object"&&!Array.isArray(v)){a[k]=dm(typeof a[k]==="object"&&a[k]?a[k]:{},v);}else{a[k]=v;}}return a;}'
    + 'function isMem(u){try{return /membership|usage-summary|dashboard\\/get-me|auth\\/(me|full_stripe|stripe_profile)|GetUserInfo|getUserPrivilege|hard-limit/i.test(u);}catch(e){return false;}}'
    + 'function isModels(u){try{return /AvailableModels|available-models/i.test(u);}catch(e){return false;}}'
    + 'function pmod(b){try{var arr=(b&&b.models)||(b&&b.data&&b.data.models);if(Array.isArray(arr)){'
    + 'for(var i=0;i<arr.length;i++){var m=arr[i];if(m&&typeof m==="object"){m.defaultOn=true;m.default_on=true;}}}}catch(e){}return b;}'
    + 'function patchBody(b,mem,mod){if(mem){if(Array.isArray(b)){for(var i=0;i<b.length;i++){if(b[i]&&typeof b[i]==="object"){dm(b[i],MEM);}}}else if(b&&typeof b==="object"){dm(b,MEM);}}if(mod){b=pmod(b);}return b;}'
    + 'var OF=G.fetch;if(typeof OF==="function"){G.fetch=function(){var a=arguments;'
    + 'return OF.apply(this,a).then(function(r){try{var u=(a[0]&&a[0].url)?a[0].url:a[0];'
    + 'var mem=isMem(u),mod=isModels(u);if(!mem&&!mod){return r;}'
    + 'return r.clone().text().then(function(txt){var b;try{b=JSON.parse(txt);}catch(e){return r;}'
    + 'try{b=patchBody(b,mem,mod);}catch(e){}'
    + 'try{return new Response(JSON.stringify(b),{status:r.status,statusText:r.statusText,headers:r.headers});}catch(e){return r;}},'
    + 'function(){return r;});}catch(e){return r;}});};}}catch(e){}})();'
)

# 只往这两个 renderer 包注入会员伪装（有 fetch/window）。
MEMBERSHIP_TARGET_NAMES = ("workbench.desktop.main.js", "workbench.glass.main.js")
# 通用匹配「任意版本」的 membership 注入片段（marker 到第一个 IIFE 结尾 })(); ），用于刷新/删除旧片段。
MEMBERSHIP_SNIPPET_RE = re.compile(re.escape(SAND_MEMBERSHIP_MARKER) + r"[\s\S]*?\}\)\(\);")
LEGACY_SAND_CLIENT_MARKER = "/*K" + "C_SAND_CLIENT_V1*/"
LEGACY_SAND_ELIGIBILITY_MARKER = "/*K" + "C_SAND_ELIGIBILITY_V1*/"
CLIENT_MARKER_PATTERN = re.escape(SAND_CLIENT_MARKER)
CLIENT_EXISTING_MARKER_PATTERN = re.escape(SAND_CLIENT_EXISTING_MARKER)
ELIGIBILITY_MARKER_PATTERN = re.escape(SAND_ELIGIBILITY_MARKER)
LEGACY_CLIENT_MARKER_PATTERN = re.escape(LEGACY_SAND_CLIENT_MARKER)
LEGACY_ELIGIBILITY_MARKER_PATTERN = re.escape(LEGACY_SAND_ELIGIBILITY_MARKER)
CLIENT_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_CLIENT(?:_(?:MODE|EXISTING))?_V1\*/"
ELIGIBILITY_MARKER_GUARD_PATTERN = r"/\*[A-Z0-9_]*SAND_ELIGIBILITY(?:_MODE)?_V1\*/"
SAND_ONBOARDING_URL = "https://cursor.com/bot/onboarding?product=grok-bot"

ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[36m"

_COLOR_ENABLED = True


TARGET_SPECS: Tuple[Tuple[str, Optional[str]], ...] = (
    ("out/main.js", None),
    ("out/vs/workbench/api/worker/extensionHostWorkerMain.js", None),
    ("out/vs/workbench/api/node/extensionHostProcess.js", None),
    ("out/vs/workbench/workbench.glass.main.js", None),
    ("out/vs/workbench/workbench.desktop.main.js", None),
    ("extensions/cursor-always-local/dist/main.js", "cursor-always-local"),
    (
        "extensions/cursor-local-agent-runtime/dist/main.js",
        "cursor-local-agent-runtime",
    ),
    ("extensions/cursor-agent-host/dist/main.js", "cursor-agent-host"),
    ("extensions/cursor-agent-exec/dist/main.js", "cursor-agent-exec"),
    ("extensions/cursor-agent-host/dist/657.js", None),
    ("extensions/cursor-agent-host/dist/675.js", None),
    ("extensions/cursor-agent-host/dist/478.js", None),
    ("extensions/cursor-agent-host/dist/477.js", None),
    # 3.18.25：478.js 重打包为 61.js（managed-local 路由 / 交互注册表 / client-type header）。
    ("extensions/cursor-agent-host/dist/61.js", None),
)

EXT_HOST_REL = "out/vs/workbench/api/node/extensionHostProcess.js"

ELIGIBILITY_PREFIXES: Tuple[str, ...] = (
    "function r4g(e){const{adminSettingsService:t",
    "function Vj_(t){const{adminSettingsService:e",
    "function inf(e){const{adminSettingsService:t",
    "function HSy(t){const{adminSettingsService:e",
    "function Q_f(e){const{adminSettingsService:t",
    "function BpS(t){const{adminSettingsService:e",
)


class SandToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class CursorLayout:
    install_root: Path
    app_root: Path
    product_json: Path
    executable: Path
    target_paths: Tuple[Path, ...]
    ext_host_path: Optional[Path]
    version: str


@dataclass(frozen=True)
class PlannedFile:
    original: bytes
    next_bytes: bytes
    mode: int


@dataclass
class PatchStats:
    is_glass: int = 0
    object_header: int = 0
    set_header: int = 0
    eligibility: int = 0
    adopted_sand: int = 0
    migrated_client: int = 0
    migrated_eligibility: int = 0
    model_unlock: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    move_exec: int = 0
    model_route: int = 0
    local_model: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0
    dns_node: int = 0
    feature_flags: int = 0
    exec_bridge: int = 0
    sand_rpc: int = 0
    ctx_window: int = 0
    local_agent: int = 0

    @property
    def total(self) -> int:
        return (
            self.sand_rpc
            + self.ctx_window
            + self.local_agent
            + self.exec_bridge
            + self.is_glass
            + self.object_header
            + self.set_header
            + self.eligibility
            + self.model_unlock
            + self.migrated_client
            + self.migrated_eligibility
            + self.managed_local_route
            + self.local_runtime_load
            + self.move_exec
            + self.model_route
            + self.local_model
            + self.direct_stream
            + self.agent_host_enablement
            + self.agent_host_identity
            + self.dns_node
            + self.feature_flags
        )


@dataclass
class RemoveStats:
    client_type: int = 0
    eligibility: int = 0
    managed_local_route: int = 0
    local_runtime_load: int = 0
    move_exec: int = 0
    model_route: int = 0
    local_model: int = 0
    direct_stream: int = 0
    agent_host_enablement: int = 0
    agent_host_identity: int = 0
    dns_node: int = 0
    feature_flags: int = 0
    exec_bridge: int = 0
    sand_rpc: int = 0
    ctx_window: int = 0
    local_agent: int = 0

    @property
    def total(self) -> int:
        return (
            self.sand_rpc
            + self.ctx_window
            + self.local_agent
            + self.exec_bridge
            + self.client_type
            + self.eligibility
            + self.managed_local_route
            + self.local_runtime_load
            + self.move_exec
            + self.model_route
            + self.local_model
            + self.direct_stream
            + self.agent_host_enablement
            + self.agent_host_identity
            + self.dns_node
            + self.feature_flags
        )


@dataclass(frozen=True)
class PatchStatus:
    client_markers: int
    eligibility_markers: int
    ide_matches: int
    external_sand_matches: int
    external_marker_count: int
    legacy_client_markers: int
    legacy_eligibility_markers: int
    patched_files: Tuple[Path, ...]
    managed_local_route_markers: int = 0
    local_runtime_load_markers: int = 0
    move_exec_markers: int = 0
    model_route_markers: int = 0
    local_model_markers: int = 0
    direct_stream_markers: int = 0
    agent_host_enablement_markers: int = 0
    agent_host_identity_markers: int = 0
    dns_node_markers: int = 0
    feature_flag_markers: int = 0
    exec_bridge_markers: int = 0
    sand_rpc_markers: int = 0
    ctx_window_markers: int = 0
    local_agent_markers: int = 0
    dns_hosts_installed: bool = False
    dns_hijacked: bool = False

    @property
    def installed(self) -> bool:
        return (
            self.client_markers
            + self.eligibility_markers
            + self.legacy_client_markers
            + self.legacy_eligibility_markers
            + self.managed_local_route_markers
            + self.local_runtime_load_markers
            + self.move_exec_markers
            + self.model_route_markers
            + self.local_model_markers
            + self.direct_stream_markers
            + self.agent_host_enablement_markers
            + self.agent_host_identity_markers
            + self.dns_node_markers
            + self.feature_flag_markers
            + self.exec_bridge_markers
            + self.sand_rpc_markers
            + self.ctx_window_markers
            + self.local_agent_markers
            > 0
        )

    @property
    def dns_ready(self) -> bool:
        # hosts 写入即视为补丁侧 DNS 完成；Clash fake-ip 可能仍让系统解析不一致，不因此判失败。
        return self.dns_hosts_installed

    @property
    def stream_mode_installed(self) -> bool:
        identity_ok = (
            self.agent_host_enablement_markers > 0
            and self.agent_host_identity_markers > 0
        )
        if self.direct_stream_markers > 0:
            return (
                identity_ok
                and self.managed_local_route_markers > 0
                and self.direct_stream_markers > 0
            )
        return (
            identity_ok
            and self.local_runtime_load_markers > 0
            and self.move_exec_markers > 0
            and self.managed_local_route_markers > 0
            and self.model_route_markers > 0
            and self.local_model_markers > 0
        )


def _compile_client_rules() -> Tuple[Tuple[str, re.Pattern[str]], ...]:
    marker_guard = rf"(?!{CLIENT_MARKER_GUARD_PATTERN})"
    return (
        (
            "is_glass",
            re.compile(
                rf"(isGlass\s*\?\s*[\"']glass[\"']\s*:\s*)([\"'])(ide|sand|agent)\2{marker_guard}"
            ),
        ),
        (
            "object_header",
            re.compile(
                rf"([\"']x-cursor-client-type[\"']\s*:\s*)([\"'])(ide|sand|agent)\2{marker_guard}"
            ),
        ),
        (
            "set_header",
            re.compile(
                rf"(header\.set\(\s*[\"']x-cursor-client-type[\"']\s*,\s*"
                rf"[A-Za-z_$][A-Za-z0-9_$.]*\s*(?:\?\?|\|\|)\s*)"
                rf"([\"'])(ide|sand|agent)\2{marker_guard}"
            ),
        ),
    )


CLIENT_RULES = _compile_client_rules()

# 3.18.9 workbench 有 hre；3.18.25 把同构工厂挪到 675.js 并改名为 gre。
# 3.17.21 没有这条工厂。agent-host 478.js（3.18.25 为 61.js）都有
# managed-local 路由：闸门变量名不同（ae / J），J 在 3.17.21 就是 agent_host_local_loop。
# 打开后加载 477.js / 675.js，其中已有 InferenceService.Stream / RunInference 会话工厂
# （Moe/xK，对应 Joe/RK；3.18.25 会话类是 tre）。
# 3.17.21 还把 managed-local 白名单写死成 claude-sonnet-4-6，必须一并绕过。
# managed-local 下本地工具走 477.js resourceAccessor.get(EM._A)；move_exec OFF 时用
# cursor-agent-exec 注册 executor，Symbol 与 agent-host 46693 不一致 → execute 全挂。
# 必须强制 cursor_agent_host_move_exec，改走 agent-host-exec(323.js) 共享 46693。
MANAGED_LOCAL_ROUTE_ORIGINAL = (
    'try{return(yield o.checkFeatureGate(ae))?'
    '{runtime:"managed-local",reason:"eligible"}:'
    '{runtime:"connect",reason:"gate-off"}}catch(e)'
)
MANAGED_LOCAL_ROUTE_PATCHED = (
    "try{return"
    + SAND_MANAGED_LOCAL_ROUTE_MARKER
    + '{runtime:"managed-local",reason:"sand-client"}}catch(e)'
)
MANAGED_LOCAL_ROUTE_RE = re.compile(
    r'try\{return\(yield o\.checkFeatureGate\([A-Za-z_$][A-Za-z0-9_$]*\)\)\?'
    r'\{runtime:"managed-local",reason:"eligible"\}:'
    r'\{runtime:"connect",reason:"gate-off"\}\}catch\(e\)'
)
MANAGED_LOCAL_RB_RE = re.compile(
    r"try\{return"
    + re.escape(SAND_MANAGED_LOCAL_ROUTE_MARKER)
    + re.escape(SAND_MANAGED_LOCAL_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_MANAGED_LOCAL_RB_SUFFIX)
    + r'\{runtime:"managed-local",reason:"sand-client"\}\}catch\(e\)'
)
MODEL_NOT_SUPPORTED_RE = re.compile(
    r'e\.modelId!==[A-Za-z_$][A-Za-z0-9_$]*\.[A-Za-z_$][A-Za-z0-9_$]*'
    r'\?"model-not-supported":'
)
MODEL_ROUTE_RB_RE = re.compile(
    r"!1"
    + re.escape(SAND_MODEL_ROUTE_MARKER)
    + re.escape(SAND_MODEL_ROUTE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_MODEL_ROUTE_RB_SUFFIX)
    + r'\?"model-not-supported":'
)
# 478.js 路由 `e.requestedMode!==xyI.AGENT` 把非 Agent 模式全部判 mode-not-supported →
# connect → Sand 被拒（3.17.21 实测日志：子代理子 turn 的 mode 是 0/UNSPECIFIED，
# 用户在 Ask/Plan 模式下发消息同样命中）。connect 在 sand 身份下必失败，而 managed-local
# 的 Doe() 本身带 Plan/Ask/Project 的 prompt 与工具切换，所以整段条件置 !1，原文进 RB。
# 2.2.2/2.2.3 曾用「仅放行 0/undefined」形态，MODE_ROUTE_LEGACY_RB_RE 负责识别并还原。
MODE_NOT_SUPPORTED_RE = re.compile(
    r'e\.requestedMode!==[A-Za-z_$][A-Za-z0-9_$]*\.[A-Za-z_$][A-Za-z0-9_$]*\.AGENT'
    r'\?"mode-not-supported":'
)
MODE_ROUTE_RB_RE = re.compile(
    r"!1"
    + re.escape(SAND_MODE_ROUTE_MARKER)
    + re.escape(SAND_MODE_ROUTE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_MODE_ROUTE_RB_SUFFIX)
    + r'\?"mode-not-supported":'
)
MODE_ROUTE_LEGACY_RB_RE = re.compile(
    r"\(void 0!==e\.requestedMode&&0!==e\.requestedMode&&[^()]*\)"
    + re.escape(SAND_MODE_ROUTE_MARKER)
    + re.escape(SAND_MODE_ROUTE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_MODE_ROUTE_RB_SUFFIX)
    + r'\?"mode-not-supported":'
)
# 478.js 把子代理 turn 的 subagentTypeName / parentAgentToolCallId 算进
# hasUnsupportedRunOptions，在 feature-gate 之前就改道 connect。只拿掉这两项，
# customSystemPrompt / harness / excludeWorkspaceContext 仍走原逻辑。
SUBAGENT_RUN_OPTIONS_ORIGINAL = (
    "void 0!==e.runOptions.subagentTypeName"
    "||void 0!==e.runOptions.parentAgentToolCallId"
)
# 3.18.25 61.js 在两项后面多了 directMetaParentChildSubagent；必须整段替换，
# 否则留下 `||!0===...` 仍会把子代理 turn 改道 connect。
SUBAGENT_RUN_OPTIONS_RE = re.compile(
    re.escape(SUBAGENT_RUN_OPTIONS_ORIGINAL)
    + r"(?:\|\|!0===e\.runOptions\.directMetaParentChildSubagent)?"
)
SUBAGENT_ROUTE_RB_RE = re.compile(
    r"!1"
    + re.escape(SAND_SUBAGENT_ROUTE_MARKER)
    + re.escape(SAND_SUBAGENT_ROUTE_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_SUBAGENT_ROUTE_RB_SUFFIX)
)
UNSUPPORTED_LOCAL_MODEL_RE = re.compile(
    r"if\((e\.modelId!==[A-Za-z_$][A-Za-z0-9_$]*\.[A-Za-z_$][A-Za-z0-9_$]*)\)"
    r"(throw new Error\(`Unsupported managed local model: \$\{e\.modelId\}`\);)"
)
LOCAL_MODEL_RB_RE = re.compile(
    r"if\(!1"
    + re.escape(SAND_LOCAL_MODEL_MARKER)
    + re.escape(SAND_LOCAL_MODEL_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_LOCAL_MODEL_RB_SUFFIX)
    + r"\)"
    + r"(throw new Error\(`Unsupported managed local model: \$\{e\.modelId\}`\);)"
)
LOCAL_RUNTIME_LOAD_RE = re.compile(
    r"let t=!1;try\{t=await [A-Za-z_$][A-Za-z0-9_$]*"
    r"\.cursor\.checkFeatureGate\([A-Za-z_$][A-Za-z0-9_$]*\)\}"
)
LOCAL_RUNTIME_LOAD_ORIGINAL = (
    "let t=!1;try{t=await r.cursor.checkFeatureGate(Ds)}"
)
LOCAL_RUNTIME_LOAD_PATCHED = (
    "let t=!0;"
    + SAND_LOCAL_RUNTIME_LOAD_MARKER
    + "try{t=!0}"
)
LOCAL_RUNTIME_RB_RE = re.compile(
    r"let t=!0;"
    + re.escape(SAND_LOCAL_RUNTIME_LOAD_MARKER)
    + re.escape(SAND_LOCAL_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_LOCAL_RB_SUFFIX)
    + r"try\{t=!0\}"
)
MOVE_EXEC_GATE_RE = re.compile(
    r"([A-Za-z_$][A-Za-z0-9_$]*)=await Promise\.resolve\("
    r"[A-Za-z_$][A-Za-z0-9_$]*\.cursor\.checkFeatureGate\([A-Za-z_$][A-Za-z0-9_$]*\)\)"
    r"\.catch\(\(\)=>!1\)"
)
MOVE_EXEC_RB_RE = re.compile(
    r"([A-Za-z_$][A-Za-z0-9_$]*)=\(!0"
    + re.escape(SAND_MOVE_EXEC_MARKER)
    + re.escape(SAND_MOVE_EXEC_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_MOVE_EXEC_RB_SUFFIX)
    + r"\|\|await Promise\.resolve\("
    r"[A-Za-z_$][A-Za-z0-9_$]*\.cursor\.checkFeatureGate\([A-Za-z_$][A-Za-z0-9_$]*\)\)"
    r"\.catch\(\(\)=>!1\)\)"
)
AGENT_HOST_CLI_TYPE_SET = (
    'i.header.set("x-cursor-client-type",null!==(s=null==r?void 0:r.clientType)'
    '&&void 0!==s?s:"cli")'
)
# 3.17.21：i.header / 变量 s；3.18.25 61.js：s.header / 变量 i。
AGENT_HOST_CLI_TYPE_RE = re.compile(
    r'([A-Za-z_$][A-Za-z0-9_$]*)\.header\.set\("x-cursor-client-type",'
    r'(null!==\(([A-Za-z_$][A-Za-z0-9_$]*)=null==r\?void 0:r\.clientType\)'
    r'&&void 0!==\3\?\3:"(?:cli|ide|sand)")\)'
)
AGENT_HOST_IDENTITY_ORIGINAL = 'clientIdentity:{clientType:"ide"}'
AGENT_HOST_IDENTITY_PATCHED = (
    'clientIdentity:{clientType:"sand"'
    + SAND_AGENT_HOST_IDENTITY_MARKER
    + "}"
)
DIRECT_STREAM_ANCHORS: Tuple[str, ...] = (
    "function hre(e){return t=>{return n=this,o=void 0,s=function*(){",
    "function gre(e){return t=>{return n=this,o=void 0,s=function*(){",
)
DIRECT_STREAM_ANCHOR = DIRECT_STREAM_ANCHORS[0]
ENABLE_AGENT_RETRIES_318_RE = re.compile(
    r"subagentModelOverrides:\[\],enableAgentRetries:"
    r"null!==\(([A-Za-z_$][A-Za-z0-9_$]*)=null==([A-Za-z_$][A-Za-z0-9_$]*)"
    r"\?void 0:\2\.enableAgentRetries\)&&void 0!==\1&&\1"
)
AGENT_HOST_ENABLEMENT_RE = re.compile(
    r"(this\._agentHostEnabled=)([A-Za-z_$][A-Za-z0-9_$]*)(,)"
)
AGENT_HOST_ENABLEMENT_PATCH_RE = re.compile(
    rf"([A-Za-z_$][A-Za-z0-9_$]*)=!0;"
    rf"{re.escape(SAND_AGENT_HOST_ENABLEMENT_MARKER)}"
    rf"(this\._agentHostEnabled=)\1(,)"
)


def _compile_feature_flag_off_re() -> re.Pattern[str]:
    # 长名优先，避免 cursor_agent_host 吃掉 cursor_agent_host_move_exec。
    names = "|".join(
        re.escape(name)
        for name in sorted(SAND_FEATURE_FLAGS_DEFAULT_ON, key=len, reverse=True)
    )
    return re.compile(rf"({names}):\{{client:!0,default:!1\}}")


FEATURE_FLAG_OFF_RE = _compile_feature_flag_off_re()
FEATURE_FLAG_PATCHED_RE = re.compile(
    r"([a-z0-9_]+):\{client:!0,default:!0"
    + re.escape(SAND_FEATURE_FLAG_MARKER)
    + re.escape(SAND_FF_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_FF_RB_SUFFIX)
    + r"\}"
)
# 2.0.7 错误把 group 拼成 ...!0/*marker*//*RB:原文*/{client:!0,default:
# Electron main (out/main.js ESM) 会 SyntaxError: Unexpected token '{'
BROKEN_FEATURE_FLAG_RE = re.compile(
    r"([a-z0-9_]+):\{client:!0,default:!0"
    + re.escape(SAND_FEATURE_FLAG_MARKER)
    + re.escape(SAND_FF_RB_PREFIX)
    + r"(.*?)"
    + re.escape(SAND_FF_RB_SUFFIX)
    + r"\{client:!0,default:"
)


def _compile_agent_runtime_flags_patched_re() -> re.Pattern[str]:
    # 2.0.9 旧形态：,flag:!0,.../*MARKER*/（MARKER 在字段后面）
    names = "|".join(re.escape(name) for name, _value in SAND_AGENT_RUNTIME_FLAGS)
    return re.compile(
        r"(?:,(?:" + names + r"):(?:!0|!1))+" + re.escape(SAND_AGENT_FLAGS_MARKER)
    )


AGENT_RUNTIME_FLAGS_PATCHED_RE = _compile_agent_runtime_flags_patched_re()
# 2.2.1 新形态：,/*MARKER*/flag:!0,...  只吃 MARKER 到下一个 } 之间的内容
AGENT_RUNTIME_FLAGS_NEW_RE = re.compile(
    re.escape("," + SAND_AGENT_FLAGS_MARKER) + r"[^}]*"
)


def remove_agent_runtime_flags(content: str) -> Tuple[str, int]:
    if SAND_AGENT_FLAGS_MARKER not in content:
        return content, 0
    next_content, new_n = AGENT_RUNTIME_FLAGS_NEW_RE.subn("", content)
    next_content, old_n = AGENT_RUNTIME_FLAGS_PATCHED_RE.subn("", next_content)
    residual = next_content.count(SAND_AGENT_FLAGS_MARKER)
    if residual:
        next_content = next_content.replace(SAND_AGENT_FLAGS_MARKER, "")
    return next_content, new_n + old_n + residual


def apply_agent_runtime_flags(content: str) -> Tuple[str, int]:
    """往 managed-local 运行期 featureFlags 对象追加客户端子代理开关。

    对象在 3.17.21 叫 Roe、3.18.25 叫 xre，故按字段签名匹配而非变量名。
    """
    next_content, removed = remove_agent_runtime_flags(content)
    match = ROE_DECL_RE.search(next_content)
    if match is None:
        return next_content, removed
    if f"featureFlags:{match.group(1)}" not in next_content:
        return next_content, removed
    fields = ",".join(
        f"{name}:{value}" for name, value in SAND_AGENT_RUNTIME_FLAGS
    )
    decl = match.group(0)
    patched = decl[:-1] + "," + SAND_AGENT_FLAGS_MARKER + fields + "}"
    next_content = next_content[: match.start()] + patched + next_content[match.end() :]
    return next_content, removed + 1


# 2.0.7 的损坏形态里，RB 注释结束后紧跟 "{client:!0,default:"；
# 正常补丁那里是 "}"。用这个字面量做前置判断，避免对 47MB 跑带回溯的正则（约 1.4s）。
BROKEN_FEATURE_FLAG_HINT = SAND_FF_RB_SUFFIX + "{client:!0,default:"


def _has_broken_feature_flags(content: str) -> bool:
    return BROKEN_FEATURE_FLAG_HINT in content


def _repair_broken_feature_flags(content: str) -> Tuple[str, int]:
    if not _has_broken_feature_flags(content):
        return content, 0
    next_content, count = BROKEN_FEATURE_FLAG_RE.subn(
        lambda match: match.group(2),
        content,
    )
    return next_content, count


def apply_feature_flag_defaults(content: str) -> Tuple[str, int]:
    next_content, repaired = _repair_broken_feature_flags(content)
    if SAND_FEATURE_FLAG_MARKER in next_content:
        return next_content, repaired

    def _enable_flag(match: re.Match[str]) -> str:
        original = match.group(0)
        name = match.group(1)
        return (
            f"{name}:{{client:!0,default:!0"
            f"{SAND_FEATURE_FLAG_MARKER}"
            f"{SAND_FF_RB_PREFIX}{original}{SAND_FF_RB_SUFFIX}"
            "}"
        )

    next_content, count = FEATURE_FLAG_OFF_RE.subn(_enable_flag, next_content)
    if _has_broken_feature_flags(next_content):
        raise SandToolError("Statsig 开关补丁生成了非法 JS，已中止写入以防 Cursor 无法启动")
    return next_content, count + repaired


def remove_feature_flag_defaults(content: str) -> Tuple[str, int]:
    next_content, broken_n = _repair_broken_feature_flags(content)
    next_content, count = FEATURE_FLAG_PATCHED_RE.subn(
        lambda match: match.group(2),
        next_content,
    )
    residual = next_content.count(SAND_FEATURE_FLAG_MARKER)
    if residual:
        next_content = next_content.replace(SAND_FEATURE_FLAG_MARKER, "")
    return next_content, broken_n + count + residual


def _agent_host_module_anchor(content: str) -> Optional[str]:
    match = AGENT_HOST_MODULE_ANCHOR_RE.search(content)
    if match:
        return match.group(0)
    if AGENT_HOST_MODULE_ANCHOR in content:
        return AGENT_HOST_MODULE_ANCHOR
    return None


def _task_tool_props_decl(content: str) -> str:
    obj = _SAND_TTP_OBJECT
    if _DOE_PROVIDER_OPTIONS_SIG in content:
        obj = obj.replace("Doe({modelId:e})", "{modelId:e}")
    return ";var _sandTtp=" + SAND_TASK_TOOL_PROPS_MARKER + obj + ";"


def _find_direct_stream_anchor(content: str) -> Optional[str]:
    for anchor in DIRECT_STREAM_ANCHORS:
        if anchor in content:
            return anchor
    return None


def _direct_stream_injection(content: str = "") -> str:
    session_ctor = "Joe"
    resolved_fn = "cre"
    meta_fn = "nre"
    # 3.18.25 675.js：会话工厂是 tre；Joe 变成了 message-list 辅助类。
    if "class tre{constructor(e,t,n,o){this.client=e,this.requestedModel=t" in content:
        session_ctor = "tre"
    # 3.18.25 里 cre 是 regenerator helper，resolvedModel 映射改为 pre。
    if (
        "cre(this,void 0,void 0,function*" in content
        or "resolvedModel:pre(" in content
    ):
        resolved_fn = "pre"
    if "function are(e,t){if(void 0!==e)return{promptModelInfo" in content:
        meta_fn = "are"
    return (
        "{"
        + SAND_DIRECT_STREAM_MARKER
        + 'const n=t.requestedModel;'
        'if(void 0===n)throw new Error("Sand direct Stream requires requestedModel");'
        'const o=String(n.modelId||""),i=o.toLowerCase(),'
        'r=new Map(n.parameters.map(e=>[e.id,e.value])),'
        f"s=new {session_ctor}(e,n,void 0,void 0).getSession(),"
        'p={getExecutor:e=>new RK(s.getExecutor(e))},'
        'a={vendor:i.includes("grok")?"xai":i.includes("gemini")?"gemini":'
        'i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable")?'
        '"anthropic":i.includes("gpt")||i.includes("codex")?"openai":"unknown",'
        'promptVersion:"latest",reasoningEffort:r.get("effort"),'
        'isGrok45ProductPrompt:i.includes("grok"),'
        'isClaude4x:i.includes("claude")||i.includes("opus")||i.includes("sonnet")||i.includes("fable"),'
        'isFable5:i.includes("fable-5"),'
        'isOpus5:i.includes("opus-5")||i.includes("opus5"),'
        'isOpus48:i.includes("opus-4.8")||i.includes("opus48"),'
        'isOpus46:i.includes("opus-4.6")||i.includes("opus46"),'
        'isOpus45:i.includes("opus-4.5")||i.includes("opus45"),'
        'isSonnet45:i.includes("sonnet-4.5")||i.includes("sonnet45"),'
        'isSonnet4:i.includes("sonnet-4")||i.includes("sonnet4"),'
        'isGemini3:i.includes("gemini-3")||i.includes("gemini3"),'
        'isGpt56:i.includes("gpt-5.6")||i.includes("gpt5.6"),'
        'isGpt55:i.includes("gpt-5.5")||i.includes("gpt5.5"),'
        'isGpt54:i.includes("gpt-5.4")||i.includes("gpt5.4"),'
        'isGpt53Codex:i.includes("gpt-5.3-codex"),'
        'isGpt52Codex:i.includes("gpt-5.2-codex"),'
        'isCodexFamily:i.includes("codex"),isGpt5Family:i.includes("gpt-5")};'
        f"return{{promptSession:s,promptToolSession:p,attempt:{{resolvedModel:{resolved_fn}(n),"
        'supportsSelfSummary:!0'
        + SAND_SELF_SUMMARY_MARKER
        + ',routedModelDisplayName:o,'
        f"resolvedModelMetadata:{meta_fn}(a,o),finish:()=>Promise.resolve()}}}}"
        + "}"
    )


def _strip_direct_stream_injection(content: str) -> Tuple[str, int]:
    needle = "{" + SAND_DIRECT_STREAM_MARKER
    idx = content.find(needle)
    if idx < 0:
        residual = content.count(SAND_DIRECT_STREAM_MARKER)
        if residual:
            return content.replace(SAND_DIRECT_STREAM_MARKER, ""), residual
        return content, 0
    depth = 0
    pos = idx
    while pos < len(content):
        ch = content[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return content[:idx] + content[pos + 1 :], 1
        pos += 1
    return content.replace(SAND_DIRECT_STREAM_MARKER, "", 1), 1


def _strip_sand_ttp_decl(content: str) -> Tuple[str, int]:
    """去掉 `;var _sandTtp=MARKER{...};`，对象字面量可变，按括号配对删除。"""
    prefix = TASK_TOOL_PROPS_DECL_PREFIX
    idx = content.find(prefix)
    if idx < 0:
        return content, 0
    brace_at = idx + len(prefix)
    if brace_at >= len(content) or content[brace_at] != "{":
        return content.replace(SAND_TASK_TOOL_PROPS_MARKER, "", 1), 1
    depth = 0
    pos = brace_at
    while pos < len(content):
        ch = content[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = pos + 1
                if end < len(content) and content[end] == ";":
                    end += 1
                return content[:idx] + content[end:], 1
        pos += 1
    return content.replace(SAND_TASK_TOOL_PROPS_MARKER, "", 1), 1


def apply_sand_rpc_lite(content: str) -> Tuple[str, int]:
    """477.js / 675.js：注入 taskToolProps，使 managed-local 路径能注册 TASK 工具。"""
    next_content, removed = remove_sand_rpc_lite(content)
    if TASK_TOOL_PROPS_VOID not in next_content:
        return next_content, removed
    count = removed
    anchor = _agent_host_module_anchor(next_content)
    decl = _task_tool_props_decl(next_content)
    if anchor and TASK_TOOL_PROPS_DECL_PREFIX not in next_content:
        next_content = next_content.replace(
            anchor,
            anchor + decl,
            1,
        )
        count += 1
    if TASK_TOOL_PROPS_VOID in next_content:
        next_content = next_content.replace(
            TASK_TOOL_PROPS_VOID, TASK_TOOL_PROPS_REF, 1
        )
        count += 1
    return next_content, count


def apply_ctx_window(content: str) -> Tuple[str, int]:
    """477.js / 675.js：Context Usage 分母按用户选的 context 参数（1m/300k）换算，而非服务端写死值。"""
    if SAND_CTX_WINDOW_MARKER in content:
        return content, 0
    anchor = _agent_host_module_anchor(content)
    if CTX_WINDOW_USAGE_ORIGINAL not in content or not anchor:
        return content, 0
    next_content = content.replace(
        anchor, anchor + CTX_WINDOW_DECL, 1
    )
    next_content = next_content.replace(
        CTX_WINDOW_USAGE_ORIGINAL, CTX_WINDOW_USAGE_PATCHED, 1
    )
    return next_content, 2


def apply_simple_replacements(content: str) -> Tuple[str, int]:
    next_content = content
    count = 0
    for original, patched in SIMPLE_REPLACEMENTS:
        if patched in next_content or original not in next_content:
            continue
        next_content = next_content.replace(original, patched, 1)
        count += 1
    if SAND_SUBAGENT_RETRY_MARKER not in next_content:
        next_content, n318 = ENABLE_AGENT_RETRIES_318_RE.subn(
            "subagentModelOverrides:[],enableAgentRetries:!0"
            + SAND_SUBAGENT_RETRY_MARKER,
            next_content,
            count=1,
        )
        count += n318
    return next_content, count


def remove_simple_replacements(content: str) -> Tuple[str, int]:
    next_content = content
    count = 0
    for original, patched in SIMPLE_REPLACEMENTS:
        n = next_content.count(patched)
        if n:
            next_content = next_content.replace(patched, original)
            count += n
    if SAND_SUBAGENT_RETRY_MARKER in next_content:
        next_content, n318 = re.subn(
            r"subagentModelOverrides:\[\],enableAgentRetries:!0"
            + re.escape(SAND_SUBAGENT_RETRY_MARKER),
            "subagentModelOverrides:[],enableAgentRetries:null!==(u=null==v?void 0:v.enableAgentRetries)&&void 0!==u&&u",
            next_content,
            count=1,
        )
        # 上面写死 u/v 只覆盖 3.18.25 当前包；若没还原成 ternary，再剥 marker。
        count += n318
    for marker in (
        SAND_SUBAGENT_RETRY_MARKER,
        SAND_MAX_RETRIES_MARKER,
        SAND_INTERACTION_ID_MARKER,
    ):
        residual = next_content.count(marker)
        if residual:
            next_content = next_content.replace(marker, "")
            count += residual
    return next_content, count


def apply_local_agent_config(content: str) -> Tuple[str, int]:
    """477.js / 675.js Doe()：补后台摘要阈值 + 按 modelId 计算 modelInfo。"""
    next_content = content
    count = 0
    if SAND_BG_SUMMARY_MARKER not in next_content:
        if DOE_TAIL_ORIGINAL in next_content:
            next_content = next_content.replace(DOE_TAIL_ORIGINAL, DOE_TAIL_PATCHED, 1)
            count += 1
        elif DOE_TAIL_318_ORIGINAL in next_content:
            next_content = next_content.replace(
                DOE_TAIL_318_ORIGINAL, DOE_TAIL_318_PATCHED, 1
            )
            count += 1
    if SAND_MODEL_INFO_MARKER not in next_content and MODEL_INFO_ORIGINAL in next_content:
        next_content = next_content.replace(MODEL_INFO_ORIGINAL, MODEL_INFO_PATCHED, 1)
        count += 1
    return next_content, count


def remove_local_agent_config(content: str) -> Tuple[str, int]:
    next_content = content
    count = 0
    if DOE_TAIL_PATCHED in next_content:
        next_content = next_content.replace(DOE_TAIL_PATCHED, DOE_TAIL_ORIGINAL, 1)
        count += 1
    elif DOE_TAIL_318_PATCHED in next_content:
        next_content = next_content.replace(
            DOE_TAIL_318_PATCHED, DOE_TAIL_318_ORIGINAL, 1
        )
        count += 1
    next_content, mi_n = MODEL_INFO_PATCHED_RE.subn(MODEL_INFO_ORIGINAL, next_content)
    count += mi_n
    for marker in (
        SAND_BG_SUMMARY_MARKER,
        SAND_MODEL_INFO_MARKER,
        SAND_MODEL_INFO_END_MARKER,
    ):
        residual = next_content.count(marker)
        if residual:
            next_content = next_content.replace(marker, "")
            count += residual
    return next_content, count


def remove_ctx_window(content: str) -> Tuple[str, int]:
    if SAND_CTX_WINDOW_MARKER not in content:
        return content, 0
    next_content = content
    count = 0
    if CTX_WINDOW_USAGE_PATCHED in next_content:
        next_content = next_content.replace(
            CTX_WINDOW_USAGE_PATCHED, CTX_WINDOW_USAGE_ORIGINAL, 1
        )
        count += 1
    next_content, decl_n = CTX_WINDOW_DECL_RE.subn("", next_content)
    count += decl_n
    for marker in (SAND_CTX_WINDOW_MARKER, SAND_CTX_WINDOW_END_MARKER):
        residual = next_content.count(marker)
        if residual:
            next_content = next_content.replace(marker, "")
            count += residual
    return next_content, count


def remove_sand_rpc_lite(content: str) -> Tuple[str, int]:
    next_content = content
    count = 0
    if TASK_TOOL_PROPS_REF in next_content:
        next_content = next_content.replace(
            TASK_TOOL_PROPS_REF, TASK_TOOL_PROPS_VOID, 1
        )
        count += 1
    next_content, decl_n = _strip_sand_ttp_decl(next_content)
    count += decl_n
    residual = next_content.count(SAND_TASK_TOOL_PROPS_MARKER)
    if residual:
        next_content = next_content.replace(SAND_TASK_TOOL_PROPS_MARKER, "")
        count += residual
    return next_content, count


def _platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    raise SandToolError("当前仅支持 Windows 和 macOS")


def _enable_windows_ansi() -> bool:
    if sys.platform != "win32":
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        for handle_id in (-11, -12):
            handle = kernel32.GetStdHandle(handle_id)
            if handle in (0, -1):
                continue
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                continue
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        return True
    except Exception:
        return False


def _configure_console() -> None:
    global _COLOR_ENABLED
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    if os.environ.get("NO_COLOR"):
        _COLOR_ENABLED = False
        return
    _COLOR_ENABLED = _enable_windows_ansi() and sys.stdout.isatty()


def colorize(text: str, *codes: str) -> str:
    if not _COLOR_ENABLED or not codes:
        return text
    return "".join(codes) + text + ANSI_RESET


def print_warn(text: str) -> None:
    print(colorize(text, ANSI_YELLOW))


def print_error(text: str) -> None:
    print(colorize(text, ANSI_RED), file=sys.stderr)


class LoadingSpinner:
    def __init__(self, message: str = "处理中") -> None:
        self.message = message
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "LoadingSpinner":
        if sys.stdout.isatty():
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        else:
            print(colorize(self.message + "...", ANSI_BLUE), flush=True)
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            print("\r" + " " * 48 + "\r", end="", flush=True)

    def _run(self) -> None:
        frames = ("|", "/", "-", "\\")
        index = 0
        while not self._stop.wait(0.1):
            text = f"{frames[index % 4]} {self.message}"
            print("\r" + colorize(text, ANSI_BLUE), end="", flush=True)
            index += 1


def _config_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "SandClientMode" / "sand-client-cli"
        return Path.home() / "AppData" / "Local" / "SandClientMode" / "sand-client-cli"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "SandClientMode"
            / "sand-client-cli"
        )
    return Path.home() / ".config" / "SandClientMode" / "sand-client-cli"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _path_key(path: Path) -> str:
    normalized = str(path.resolve())
    return os.path.normcase(normalized)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _product_checksum(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def _atomic_write(path: Path, data: bytes, mode: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / (
        f".{path.name}.sand-client-{os.getpid()}-{time.time_ns()}.tmp"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd: Optional[int] = None
    try:
        fd = os.open(str(temp), flags, 0o600)
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = None
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp, stat.S_IMODE(mode))
        try:
            os.replace(temp, path)
        except PermissionError:
            original_mode: Optional[int] = None
            if path.exists():
                original_mode = stat.S_IMODE(path.stat().st_mode)
                os.chmod(path, original_mode | stat.S_IWRITE)
            try:
                os.replace(temp, path)
            except BaseException:
                if original_mode is not None and path.exists():
                    try:
                        os.chmod(path, original_mode)
                    except OSError:
                        pass
                raise
        if mode is not None:
            os.chmod(path, stat.S_IMODE(mode))
    finally:
        if fd is not None:
            os.close(fd)
        try:
            if temp.exists():
                temp.unlink()
        except OSError:
            pass


def _write_json_atomic(path: Path, value: Mapping[str, object]) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, data, 0o600)


def _load_config() -> Mapping[str, object]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SandToolError(
            f"配置文件损坏：{path}\n请运行 set-path auto 后重新检测"
        ) from exc
    if not isinstance(value, dict) or value.get("version") != CONFIG_VERSION:
        raise SandToolError(
            f"不支持的配置文件：{path}\n请运行 set-path auto 后重新检测"
        )
    return value


def _read_product(product_path: Path) -> Mapping[str, object]:
    try:
        size = product_path.stat().st_size
        if size <= 0 or size > 1024 * 1024:
            raise SandToolError(f"product.json 大小异常：{product_path}")
        raw = product_path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except SandToolError:
        raise
    except Exception as exc:
        raise SandToolError(f"无法读取 Cursor product.json：{product_path}") from exc
    if not isinstance(value, dict):
        raise SandToolError(f"Cursor product.json 格式错误：{product_path}")
    name = str(value.get("applicationName") or value.get("nameShort") or "")
    if name.casefold() != "cursor":
        raise SandToolError(f"所选目录不是 Cursor 安装：{product_path}")
    return value


def _find_app_bundle(app_root: Path) -> Optional[Path]:
    for item in (app_root, *app_root.parents):
        if item.name.casefold() == "cursor.app":
            return item
    return None


def _candidate_app_roots(raw_path: Path) -> Iterable[Path]:
    path = raw_path
    if path.is_file():
        if path.name.casefold() == "product.json":
            path = path.parent
        else:
            path = path.parent
    current = path
    for _ in range(8):
        yield current
        yield current / "resources" / "app"
        yield current / "Resources" / "app"
        yield current / "Contents" / "Resources" / "app"
        if current.parent == current:
            break
        current = current.parent


def _resolve_executable(app_root: Path) -> Tuple[Path, Path]:
    if sys.platform == "win32":
        if app_root.parent.name.casefold() == "resources":
            install_root = app_root.parent.parent
        else:
            install_root = app_root
        candidates = (
            install_root / "Cursor.exe",
            install_root / "cursor.exe",
        )
    elif sys.platform == "darwin":
        bundle = _find_app_bundle(app_root)
        if bundle is None:
            raise SandToolError("macOS Cursor 路径必须位于 Cursor.app 内")
        install_root = bundle
        candidates = (bundle / "Contents" / "MacOS" / "Cursor",)
    else:
        raise SandToolError("当前仅支持 Windows 和 macOS")

    for executable in candidates:
        try:
            resolved = executable.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if resolved.is_file() and _is_within(resolved, install_root.resolve()):
            return install_root.resolve(), resolved
    raise SandToolError(f"未找到 Cursor 可执行文件：{install_root}")


def layout_from_path(value: Union[str, Path]) -> CursorLayout:
    raw_text = str(value).strip().strip('"')
    if not raw_text:
        raise SandToolError("Cursor 路径不能为空")
    if sys.platform == "win32" and (
        raw_text.startswith("\\\\") or raw_text.startswith("\\\\?\\")
    ):
        raise SandToolError("不支持 UNC 或 Windows 设备路径")

    raw = Path(raw_text).expanduser()
    if not raw.is_absolute():
        raise SandToolError(f"Cursor 路径必须是绝对路径：{raw}")
    try:
        raw = raw.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise SandToolError(f"Cursor 路径不存在：{raw}") from exc

    seen: Set[str] = set()
    last_error: Optional[Exception] = None
    for candidate in _candidate_app_roots(raw):
        try:
            app_root = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        key = _path_key(app_root)
        if key in seen:
            continue
        seen.add(key)

        product_json = app_root / "product.json"
        if not product_json.is_file():
            continue
        try:
            product_real = product_json.resolve(strict=True)
            if not _is_within(product_real, app_root):
                raise SandToolError("product.json 符号链接逃逸出 Cursor app 目录")
            product = _read_product(product_real)
            install_root, executable = _resolve_executable(app_root)

            targets: List[Path] = []
            for rel, _extension_name in TARGET_SPECS:
                target = app_root.joinpath(*rel.split("/"))
                if not target.is_file():
                    continue
                target_real = target.resolve(strict=True)
                if not _is_within(target_real, app_root):
                    raise SandToolError(f"目标文件符号链接逃逸：{target}")
                targets.append(target_real)
            if not targets:
                raise SandToolError(
                    "Cursor 使用 app.asar 或当前版本没有可识别的 Sand 目标文件"
                )

            ext_host = app_root.joinpath(*EXT_HOST_REL.split("/"))
            ext_host_real = ext_host.resolve(strict=True) if ext_host.is_file() else None
            version = str(product.get("version") or product.get("commit") or "未知")
            return CursorLayout(
                install_root=install_root,
                app_root=app_root,
                product_json=product_real,
                executable=executable,
                target_paths=tuple(targets),
                ext_host_path=ext_host_real,
                version=version,
            )
        except SandToolError as exc:
            last_error = exc
            continue

    if last_error:
        raise SandToolError(f"Cursor 路径校验失败：{last_error}") from last_error
    raise SandToolError(f"路径中未找到 Cursor resources/app：{raw}")


def _powershell_executable() -> Optional[str]:
    return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh")


def _windows_running_candidates() -> List[str]:
    powershell = _powershell_executable()
    if not powershell:
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new();"
        "Get-CimInstance Win32_Process -Filter \"Name='Cursor.exe'\" | "
        "ForEach-Object { if ($_.ExecutablePath) { $_.ExecutablePath } }"
    )
    try:
        result = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _windows_registry_candidates() -> List[str]:
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    candidates: List[str] = []
    roots = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    uninstall = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    for root in roots:
        for view in views:
            try:
                parent = winreg.OpenKey(root, uninstall, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with parent:
                index = 0
                while True:
                    try:
                        name = winreg.EnumKey(parent, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        child = winreg.OpenKey(parent, name)
                    except OSError:
                        continue
                    with child:
                        def read(name_: str) -> str:
                            try:
                                return str(winreg.QueryValueEx(child, name_)[0] or "")
                            except OSError:
                                return ""

                        display_name = read("DisplayName").strip()
                        publisher = read("Publisher").strip()
                        if display_name.casefold() != "cursor" and "anysphere" not in publisher.casefold():
                            continue
                        install_location = read("InstallLocation").strip().strip('"')
                        display_icon = read("DisplayIcon").strip().strip('"')
                        if install_location:
                            candidates.append(install_location)
                        if display_icon:
                            icon_path = re.sub(r",\s*-?\d+$", "", display_icon).strip('"')
                            candidates.append(icon_path)
    return candidates


def _mac_process_paths(strict: bool = False) -> List[Tuple[int, Path]]:
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        proc_pidpath = libproc.proc_pidpath
        proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        proc_pidpath.restype = ctypes.c_int
        result = subprocess.run(
            ["ps", "-axo", "pid="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        if strict:
            raise SandToolError("无法读取 macOS 进程可执行路径") from exc
        return []
    if result.returncode != 0:
        if strict:
            raise SandToolError("无法读取 macOS 进程可执行路径")
        return []
    values: List[Tuple[int, Path]] = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        buffer = ctypes.create_string_buffer(4096)
        length = proc_pidpath(pid, buffer, len(buffer))
        if length <= 0:
            continue
        try:
            executable = Path(os.fsdecode(buffer.value)).resolve(strict=False)
        except (OSError, ValueError):
            continue
        values.append((pid, executable))
    return values


def _bundle_for_executable(executable: Path) -> Optional[Path]:
    for item in (executable, *executable.parents):
        if item.name.casefold() == "cursor.app":
            return item
    return None


def _mac_running_candidates() -> List[str]:
    values: Dict[str, str] = {}
    for _pid, executable in _mac_process_paths():
        bundle = _bundle_for_executable(executable)
        if bundle is not None:
            values.setdefault(_path_key(bundle), str(bundle))
    return list(values.values())


def _mac_spotlight_candidates() -> List[str]:
    mdfind = shutil.which("mdfind")
    if not mdfind:
        return []
    try:
        result = subprocess.run(
            [
                mdfind,
                "kMDItemCFBundleIdentifier == 'com.todesktop.230313mzl4w4u92'",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _default_candidate_groups() -> Iterable[Tuple[str, Sequence[str]]]:
    env_candidate = os.environ.get("SAND_CURSOR_INSTALL_DIR", "").strip()
    if env_candidate:
        yield "环境变量 SAND_CURSOR_INSTALL_DIR", (env_candidate,)

    if sys.platform == "win32":
        # 先查默认安装目录（纯 Path 判断，秒级、无子进程），命中就不必跑慢的 PowerShell。
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
        defaults = [
            str(Path(local) / "Programs" / "Cursor") if local else "",
            str(Path(local) / "Programs" / "cursor") if local else "",
            str(Path(local) / "Cursor") if local else "",
            str(Path(program_files) / "Cursor"),
            str(Path(program_files_x86) / "Cursor") if program_files_x86 else "",
        ]
        yield "Windows 默认目录", tuple(x for x in defaults if x)
        yield "Windows 安装登记", _windows_registry_candidates()
        # 运行中的 Cursor 用 PowerShell CIM 查询较慢，放最后兜底（非默认路径安装时才需要）。
        yield "运行中的 Cursor", _windows_running_candidates()
    elif sys.platform == "darwin":
        yield "运行中的 Cursor", _mac_running_candidates()
        yield "macOS Spotlight", _mac_spotlight_candidates()
        yield "macOS 默认目录", (
            "/Applications/Cursor.app",
            str(Path.home() / "Applications" / "Cursor.app"),
        )

    path_cursor = shutil.which("cursor")
    if path_cursor:
        yield "PATH", (path_cursor,)


def _valid_layouts(values: Sequence[str]) -> List[CursorLayout]:
    layouts: Dict[str, CursorLayout] = {}
    for value in values:
        if not value:
            continue
        try:
            layout = layout_from_path(value)
        except SandToolError:
            continue
        layouts.setdefault(_path_key(layout.app_root), layout)
    return list(layouts.values())


def resolve_cursor_layout() -> CursorLayout:
    configured = _load_config().get("cursorInstallRoot")
    if isinstance(configured, str) and configured.strip():
        try:
            return layout_from_path(configured)
        except SandToolError as exc:
            raise SandToolError(
                f"已设置的 Cursor 路径失效：{configured}\n"
                "请运行 set-path <新路径>，或运行 set-path auto 恢复自动检测"
            ) from exc

    for source, values in _default_candidate_groups():
        layouts = _valid_layouts(tuple(values))
        if len(layouts) == 1:
            return layouts[0]
        if len(layouts) > 1:
            options = "\n".join(f"  - {item.install_root}" for item in layouts)
            raise SandToolError(
                f"{source}检测到多个 Cursor 安装，请先在菜单中选择 3 设置路径：\n{options}"
            )
    raise SandToolError(
        "未检测到 Cursor 安装，请在菜单中选择 3 设置 Cursor 路径"
        "（Cursor.exe、Cursor.app 或 resources/app）"
    )


def save_cursor_path(value: str) -> Optional[CursorLayout]:
    if value.strip().casefold() in {"auto", "clear", "reset"}:
        _write_json_atomic(
            _config_path(),
            {
                "version": CONFIG_VERSION,
                "cursorInstallRoot": "",
                "lastVerifiedVersion": "",
                "updatedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
        return None

    layout = layout_from_path(value)
    _write_json_atomic(
        _config_path(),
        {
            "version": CONFIG_VERSION,
            "cursorInstallRoot": str(layout.install_root),
            "lastVerifiedVersion": layout.version,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
    )
    return layout


def _strip_orphan_hdrfix_after_paren(content: str) -> str:
    return re.sub(
        r'(header\.set\(\s*["\']x-cursor-client-type["\']\s*,\s*[^)]*\))\s*'
        + re.escape(SAND_HDRFIX_MARKER),
        r"\1",
        content,
    )


def _strip_injected_extra_headers(content: str) -> str:
    content = re.sub(
        r',\s*[A-Za-z0-9_$]+\.header\.set\(\s*["\']x-cursor-client-version["\']\s*,'
        r'\s*["\'][^"\']+["\']'
        + re.escape(SAND_VERFIX_MARKER)
        + r"(?:"
        + re.escape(SAND_VERFIX_RB_PREFIX)
        + r".*?"
        + re.escape(SAND_VERFIX_RB_SUFFIX)
        + r")?\s*\)",
        "",
        content,
    )
    content = re.sub(
        r',\s*[A-Za-z0-9_$]+\.header\.set\(\s*["\']x-sand-box-namespace["\']\s*,'
        r'\s*["\'][^"\']+["\']'
        + re.escape(SAND_NSFIX_MARKER)
        + r"\s*\)",
        "",
        content,
    )
    return content


def _apply_exec_bridges(content: str) -> Tuple[str, int]:
    next_content = content
    count = 0
    if SAND_EXEC_BRIDGE_MARKER not in next_content:
        bridge_n = next_content.count(EXEC_BRIDGE_GET_ORIGINAL)
        if bridge_n:
            next_content = next_content.replace(
                EXEC_BRIDGE_GET_ORIGINAL, EXEC_BRIDGE_GET_PATCHED
            )
            count += bridge_n
    if SAND_BR_RESOURCE_BRIDGE_MARKER not in next_content:
        br_n = next_content.count(BR_RESOURCE_GET_ORIGINAL)
        if br_n:
            next_content = next_content.replace(
                BR_RESOURCE_GET_ORIGINAL, BR_RESOURCE_GET_PATCHED
            )
            count += br_n
    return next_content, count


def apply_patch_to_content(content: str) -> Tuple[str, PatchStats]:
    stats = PatchStats()
    next_content = content
    legacy_client_re = re.compile(
        rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}"
    )
    next_content, stats.migrated_client = legacy_client_re.subn(
        lambda match: match.group(1)
        + PATCH_CLIENT_TYPE
        + match.group(1)
        + SAND_CLIENT_MARKER,
        next_content,
    )
    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    stats.migrated_eligibility = next_content.count(legacy_eligibility)
    next_content = next_content.replace(
        legacy_eligibility,
        "return!1;" + SAND_ELIGIBILITY_MARKER,
    )
    next_content = _strip_orphan_hdrfix_after_paren(next_content)
    next_content = _strip_injected_extra_headers(next_content)

    # 强制 header.set 第二实参为字面 "sand"，并写入可逆 RB（原 VAR??fallback 或原字面量）。
    header_force_pattern = re.compile(
        r'(header\.set\(\s*["\']x-cursor-client-type["\']\s*,\s*)'
        r'(?:([A-Za-z0-9_$.]+)(\?\?|\|\|)\s*)?'
        r'(["\'])(ide|sand|agent)\4'
        r'(?:/\*SAND[A-Z0-9_]*_V1\*/)*'
        r'(?:/\*SAND_HDRFIX_RB:(.*?)\*/)?'
    )

    def _force_header(match: "re.Match[str]") -> str:
        stats.set_header += 1
        q = match.group(4)
        current = match.group(5)
        var, op = match.group(2), match.group(3)
        existing_rb = match.group(6)
        if existing_rb:
            original = existing_rb
        elif var and op:
            original = f"{var}{op}{q}{current}{q}"
        else:
            original = f"{q}{current}{q}"
        rb = f"{SAND_HDRFIX_RB_PREFIX}{original}{SAND_HDRFIX_RB_SUFFIX}"
        return (
            f"{match.group(1)}{q}{PATCH_CLIENT_TYPE}{q}"
            f"{SAND_HDRFIX_MARKER}{rb}"
        )

    next_content = header_force_pattern.sub(_force_header, next_content)

    for key, rule in CLIENT_RULES:
        def replace_client(match: re.Match[str], stat_key: str = key) -> str:
            current = match.group(3)
            setattr(stats, stat_key, getattr(stats, stat_key) + 1)
            if current == PATCH_CLIENT_TYPE:
                stats.adopted_sand += 1
                marker = SAND_CLIENT_EXISTING_MARKER
            else:
                marker = SAND_CLIENT_MARKER
            return (
                match.group(1)
                + match.group(2)
                + PATCH_CLIENT_TYPE
                + match.group(2)
                + marker
            )

        next_content = rule.sub(replace_client, next_content)

    glass_true_pattern = re.compile(
        r'(isGlass\?)(["\'])glass\2(:)(["\'])(?:ide|sand|agent)\4'
    )

    def _fix_glass_true(match: "re.Match[str]") -> str:
        stats.is_glass += 1
        q1 = match.group(2)
        q2 = match.group(4)
        return (
            f"{match.group(1)}{q1}{PATCH_CLIENT_TYPE}{q1}{SAND_GLASSFIX_MARKER}"
            f"{match.group(3)}{q2}{PATCH_CLIENT_TYPE}{q2}{SAND_CLIENT_MARKER}"
        )

    next_content = glass_true_pattern.sub(_fix_glass_true, next_content)

    def _force_cli_ternary(match: "re.Match[str]") -> str:
        stats.set_header += 1
        recv = match.group(1)
        original_arg = match.group(2)
        rb = f"{SAND_HDRFIX_RB_PREFIX}{original_arg}{SAND_HDRFIX_RB_SUFFIX}"
        return (
            f'{recv}.header.set("x-cursor-client-type","sand"'
            f"{SAND_HDRFIX_MARKER}{rb})"
        )

    next_content, _cli_n = AGENT_HOST_CLI_TYPE_RE.subn(
        _force_cli_ternary, next_content, count=1
    )

    extra_after_type = re.compile(
        r'(([A-Za-z0-9_$]+)\.header\.set\(\s*["\']x-cursor-client-type["\']\s*,\s*'
        r'["\']sand["\'](?:/\*[^*]*\*/)*\s*\))'
        r'(?!\s*,\s*\2\.header\.set\(\s*["\']x-sand-box-namespace["\'])'
    )

    def _inject_extra(match: "re.Match[str]") -> str:
        recv = match.group(2)
        # 只补 Grok Bot 的 namespace；不要改 client-version。
        # Cursor 3.17 聊天走 ChatService 双向流，版本必须仍是 Cursor 自己的 3.x，
        # 改成 0.18.0 会让服务端按 Grok Bot 协议校验，从而 Connection Error。
        return (
            f"{match.group(1)},"
            f'{recv}.header.set("x-sand-box-namespace","{SAND_BOX_NAMESPACE}"'
            f"{SAND_NSFIX_MARKER})"
        )

    next_content, extra_n = extra_after_type.subn(_inject_extra, next_content)
    stats.set_header += extra_n

    ah_ns_inject = (
        AGENT_HOST_CLI_TYPE_SET
        + f',i.header.set("x-sand-box-namespace","{SAND_BOX_NAMESPACE}"'
        + SAND_NSFIX_MARKER
        + ")"
    )
    if AGENT_HOST_CLI_TYPE_SET in next_content and ah_ns_inject not in next_content:
        next_content = next_content.replace(
            AGENT_HOST_CLI_TYPE_SET, ah_ns_inject, 1
        )
        stats.set_header += 1

    # 版本无关：匹配任意「函数体第一句是 const{adminSettingsService:...}」的资格函数并注入 return!1，
    # 取代原固定混淆函数名清单（会随 Cursor 版本失效）。注入后 { 后是 return，不会重复匹配，天然幂等。
    eligibility_pattern = re.compile(
        r"(function\s+[A-Za-z0-9_$]+\([A-Za-z0-9_$]+\)\{)(const\{adminSettingsService:)"
    )

    def inject_eligibility(match: "re.Match[str]") -> str:
        stats.eligibility += 1
        return match.group(1) + "return!1;" + SAND_ELIGIBILITY_MARKER + match.group(2)

    next_content = eligibility_pattern.sub(inject_eligibility, next_content)

    # 解锁模型列表（移植自 cursor-fd unlock-membership）：
    # 免费账号的「模型选择器」判定函数体形如  ...})\{return X===M.FREE&&Y&&Z===void 0}
    # 在函数体开头插入 return!1; 让它恒为 false（不再因 FREE 锁命名模型）。原表达式作为死代码保留，可回退。
    # M 用 \w+ 泛化（不同版本变量名不同），比 cursor-fd 写死 lr 更耐版本。
    model_lock_pattern = re.compile(
        r"(hasResolvedTeamMembership:\w+,teamId:\w+\}\)\{)(return \w+===\w+\.FREE&&\w+&&\w+===void 0\})"
    )

    def inject_model_unlock(match: "re.Match[str]") -> str:
        stats.model_unlock += 1
        return match.group(1) + "return!1;" + SAND_MODEL_UNLOCK_MARKER + match.group(2)

    next_content = model_lock_pattern.sub(inject_model_unlock, next_content)

    # 会员判定改 PRO（3.8.24 实测命中）：客户端 _membershipType 读的是 storageService 里
    # cursorAuth/stripeMembershipType（值就是 "free"/"pro" 等枚举字符串）。改成 =>"pro"||原读取，
    # 短路恒返回 "pro"，让所有 ===qs.FREE 判定失效、===qs.PRO 成立。原读取保留为死代码，可回退。
    mem_pro_pattern = re.compile(r"(_membershipType=\(\)=>)(this\.storageService\.get\()")

    def inject_mem_pro(match: "re.Match[str]") -> str:
        stats.model_unlock += 1
        return match.group(1) + '"enterprise"||' + SAND_MEM_PRO_MARKER + match.group(2)

    next_content = mem_pro_pattern.sub(inject_mem_pro, next_content)
    # 刷新旧补丁里的 "pro" -> "enterprise"（旧版打的是 pro，再打补丁时升级）。
    next_content = re.sub(
        r'"pro"\|\|(' + re.escape(SAND_MEM_PRO_MARKER) + r")",
        r'"enterprise"||\1',
        next_content,
    )

    # 解锁 Max mode（3.8.24 实测命中）：hasValidPaymentMethod=async()=>{...联网查绑卡...}
    # 免费无卡返回 false → 触发「Max mode is only available to paid users」。
    # 在函数体开头插 return!0; 恒返回 true（Promise<true>），绕过绑卡守卫。负向前瞻保证幂等，可回退。
    maxmode_pattern = re.compile(r"(hasValidPaymentMethod=async\(\)=>\{)(?!return!0;)")

    def inject_maxmode(match: "re.Match[str]") -> str:
        stats.model_unlock += 1
        return match.group(1) + "return!0;" + SAND_MAXMODE_MARKER

    next_content = maxmode_pattern.sub(inject_maxmode, next_content)

    route_count = next_content.count(MANAGED_LOCAL_ROUTE_ORIGINAL)
    if SAND_MANAGED_LOCAL_ROUTE_MARKER not in next_content:
        def _force_managed_local(match: re.Match[str]) -> str:
            stats.managed_local_route += 1
            original = match.group(0)
            return (
                "try{return"
                + SAND_MANAGED_LOCAL_ROUTE_MARKER
                + SAND_MANAGED_LOCAL_RB_PREFIX
                + original
                + SAND_MANAGED_LOCAL_RB_SUFFIX
                + '{runtime:"managed-local",reason:"sand-client"}}catch(e)'
            )

        next_content, _route_n = MANAGED_LOCAL_ROUTE_RE.subn(
            _force_managed_local, next_content, count=1
        )
        if not _route_n and route_count:
            next_content = next_content.replace(
                MANAGED_LOCAL_ROUTE_ORIGINAL,
                MANAGED_LOCAL_ROUTE_PATCHED,
            )
            stats.managed_local_route += route_count

    if SAND_MODEL_ROUTE_MARKER not in next_content:
        def _force_model_route(match: re.Match[str]) -> str:
            stats.model_route += 1
            original = match.group(0)
            return (
                "!1"
                + SAND_MODEL_ROUTE_MARKER
                + SAND_MODEL_ROUTE_RB_PREFIX
                + original
                + SAND_MODEL_ROUTE_RB_SUFFIX
                + '?"model-not-supported":'
            )

        next_content, _model_n = MODEL_NOT_SUPPORTED_RE.subn(
            _force_model_route, next_content, count=1
        )

    # 2.2.2/2.2.3 的「仅放行 0/undefined」形态先还原成原文，再统一打成 !1 形态。
    next_content, _legacy_mode_n = MODE_ROUTE_LEGACY_RB_RE.subn(
        lambda match: match.group(1) + '?"mode-not-supported":', next_content
    )
    if SAND_MODE_ROUTE_MARKER not in next_content:
        def _allow_any_mode(match: re.Match[str]) -> str:
            stats.sand_rpc += 1
            original = match.group(0)
            condition = original[: original.index('?"mode-not-supported":')]
            return (
                "!1"
                + SAND_MODE_ROUTE_MARKER
                + SAND_MODE_ROUTE_RB_PREFIX
                + condition
                + SAND_MODE_ROUTE_RB_SUFFIX
                + '?"mode-not-supported":'
            )

        next_content, _mode_n = MODE_NOT_SUPPORTED_RE.subn(
            _allow_any_mode, next_content, count=1
        )

    if SAND_ACTION_ROUTE_MARKER not in next_content and ACTION_GATE_ORIGINAL in next_content:
        next_content = next_content.replace(ACTION_GATE_ORIGINAL, ACTION_GATE_PATCHED, 1)
        stats.sand_rpc += 1

    if SAND_HTTP2_GATE_MARKER not in next_content:
        def _skip_http2_gate(match: re.Match[str]) -> str:
            stats.sand_rpc += 1
            return (
                SAND_HTTP2_GATE_MARKER
                + SAND_HTTP2_GATE_RB_PREFIX
                + match.group(0)
                + SAND_HTTP2_GATE_RB_SUFFIX
            )

        next_content, _http2_n = HTTP2_GATE_RE.subn(
            _skip_http2_gate, next_content, count=1
        )

    if SAND_SUBAGENT_ROUTE_MARKER not in next_content:
        def _allow_subagent_run_options(match: re.Match[str]) -> str:
            stats.sand_rpc += 1
            original = match.group(0)
            return (
                "!1"
                + SAND_SUBAGENT_ROUTE_MARKER
                + SAND_SUBAGENT_ROUTE_RB_PREFIX
                + original
                + SAND_SUBAGENT_ROUTE_RB_SUFFIX
            )

        next_content, _sub_n = SUBAGENT_RUN_OPTIONS_RE.subn(
            _allow_subagent_run_options, next_content, count=1
        )

    if SAND_LOCAL_MODEL_MARKER not in next_content:
        def _force_local_model(match: re.Match[str]) -> str:
            stats.local_model += 1
            return (
                "if(!1"
                + SAND_LOCAL_MODEL_MARKER
                + SAND_LOCAL_MODEL_RB_PREFIX
                + match.group(1)
                + SAND_LOCAL_MODEL_RB_SUFFIX
                + ")"
                + match.group(2)
            )

        next_content, _local_model_n = UNSUPPORTED_LOCAL_MODEL_RE.subn(
            _force_local_model, next_content, count=1
        )

    if SAND_LOCAL_RUNTIME_LOAD_MARKER not in next_content:
        def _force_local_runtime(match: re.Match[str]) -> str:
            stats.local_runtime_load += 1
            original = match.group(0)
            return (
                "let t=!0;"
                + SAND_LOCAL_RUNTIME_LOAD_MARKER
                + SAND_LOCAL_RB_PREFIX
                + original
                + SAND_LOCAL_RB_SUFFIX
                + "try{t=!0}"
            )

        next_content, _runtime_n = LOCAL_RUNTIME_LOAD_RE.subn(
            _force_local_runtime, next_content, count=1
        )

    # MOVE_EXEC_GATE_RE 以变量名开头，会全文回溯（47MB 上约 2.3s）。
    # 该 gate 必然形如 X=await Promise.resolve(Y.cursor.checkFeatureGate(Z)).catch(()=>!1)，
    # 用其中最长的固定子串先判否。
    if (
        SAND_MOVE_EXEC_MARKER not in next_content
        and ".cursor.checkFeatureGate(" in next_content
        and "=await Promise.resolve(" in next_content
    ):

        def _force_move_exec(match: re.Match[str]) -> str:
            stats.move_exec += 1
            var = match.group(1)
            original = match.group(0)
            return (
                f"{var}=(!0"
                + SAND_MOVE_EXEC_MARKER
                + SAND_MOVE_EXEC_RB_PREFIX
                + original
                + SAND_MOVE_EXEC_RB_SUFFIX
                + "||"
                + original[original.index("=") + 1 :]
                + ")"
            )

        next_content, _move_exec_n = MOVE_EXEC_GATE_RE.subn(
            _force_move_exec, next_content, count=1
        )

    identity_count = next_content.count(AGENT_HOST_IDENTITY_ORIGINAL)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_ORIGINAL,
            AGENT_HOST_IDENTITY_PATCHED,
        )
        stats.agent_host_identity += identity_count

    direct_injection = _direct_stream_injection(next_content)
    stream_anchor = _find_direct_stream_anchor(next_content)
    if SAND_DIRECT_STREAM_MARKER not in next_content and stream_anchor:
        next_content = next_content.replace(
            stream_anchor,
            stream_anchor + direct_injection,
            1,
        )
        stats.direct_stream += 1

    if SAND_AGENT_HOST_ENABLEMENT_MARKER not in next_content:
        def enable_agent_host(match: re.Match[str]) -> str:
            variable = match.group(2)
            return (
                variable
                + "=!0;"
                + SAND_AGENT_HOST_ENABLEMENT_MARKER
                + match.group(1)
                + variable
                + match.group(3)
            )

        next_content, agent_host_count = AGENT_HOST_ENABLEMENT_RE.subn(
            enable_agent_host,
            next_content,
            count=1,
        )
        stats.agent_host_enablement += agent_host_count

    next_content, ff_n = apply_feature_flag_defaults(next_content)
    stats.feature_flags += ff_n
    next_content, agent_ff_n = apply_agent_runtime_flags(next_content)
    stats.feature_flags += agent_ff_n

    next_content, bridge_n = _apply_exec_bridges(next_content)
    stats.exec_bridge += bridge_n
    # ctx_window 与 sand_rpc_lite 共用 AGENT_HOST_MODULE_ANCHOR 插入声明，而 sand_rpc_lite
    # 每次都先删再插；必须让 ctx_window 先插，二次安装才不会把两段声明的顺序对调。
    next_content, ctx_n = apply_ctx_window(next_content)
    stats.ctx_window += ctx_n
    next_content, rpc_n = apply_sand_rpc_lite(next_content)
    stats.sand_rpc += rpc_n
    next_content, agent_cfg_n = apply_local_agent_config(next_content)
    stats.local_agent += agent_cfg_n
    next_content, simple_n = apply_simple_replacements(next_content)
    stats.sand_rpc += simple_n
    return next_content, stats


def remove_patch_from_content(content: str) -> Tuple[str, RemoveStats]:
    stats = RemoveStats()
    next_content = _strip_injected_extra_headers(content)
    next_content = _strip_orphan_hdrfix_after_paren(next_content)

    ver_rb_re = re.compile(
        r'["\']'
        + re.escape(SAND_CLIENT_VERSION)
        + r'["\']'
        + re.escape(SAND_VERFIX_MARKER)
        + re.escape(SAND_VERFIX_RB_PREFIX)
        + r"(.+?)"
        + re.escape(SAND_VERFIX_RB_SUFFIX)
    )
    next_content, ver_n = ver_rb_re.subn(lambda m: m.group(1), next_content)
    stats.client_type += ver_n
    next_content, ver_bare = re.subn(
        r'["\']' + re.escape(SAND_CLIENT_VERSION) + r'["\']' + re.escape(SAND_VERFIX_MARKER),
        "this.productService.version",
        next_content,
    )
    stats.client_type += ver_bare

    hdr_rb_re = re.compile(
        r'(["\'])(?:sand|agent|ide)\1'
        + re.escape(SAND_HDRFIX_MARKER)
        + re.escape(SAND_HDRFIX_RB_PREFIX)
        + r"(.+?)"
        + re.escape(SAND_HDRFIX_RB_SUFFIX)
        + r"(?:/\*SAND[A-Z0-9_]*_V1\*/)?"
    )
    next_content, hdr_rb_n = hdr_rb_re.subn(lambda m: m.group(2), next_content)
    stats.client_type += hdr_rb_n

    legacy_client_re = re.compile(
        rf"([\"'])(?:sand|agent)\1{LEGACY_CLIENT_MARKER_PATTERN}"
    )
    next_content, legacy_client_count = legacy_client_re.subn(
        lambda match: match.group(1) + "ide" + match.group(1),
        next_content,
    )
    stats.client_type += legacy_client_count
    legacy_eligibility = "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
    legacy_eligibility_count = next_content.count(legacy_eligibility)
    next_content = next_content.replace(legacy_eligibility, "")
    stats.eligibility += legacy_eligibility_count
    client_re = re.compile(rf"([\"'])(?:sand|agent)\1{CLIENT_MARKER_PATTERN}")
    existing_re = re.compile(
        rf"([\"'])(?:sand|agent)\1{CLIENT_EXISTING_MARKER_PATTERN}"
    )

    def remove_client(match: re.Match[str]) -> str:
        stats.client_type += 1
        return match.group(1) + "ide" + match.group(1)

    next_content = client_re.sub(remove_client, next_content)
    next_content, existing_count = existing_re.subn(
        lambda match: match.group(1) + "sand" + match.group(1),
        next_content,
    )
    stats.client_type += existing_count
    glassfix_re = re.compile(r"([\"'])(?:sand|agent)\1" + re.escape(SAND_GLASSFIX_MARKER))
    next_content, glassfix_count = glassfix_re.subn(
        lambda match: match.group(1) + "glass" + match.group(1),
        next_content,
    )
    stats.client_type += glassfix_count
    hdrfix_re = re.compile(r"([\"'])(?:sand|agent)\1" + re.escape(SAND_HDRFIX_MARKER))
    next_content, hdrfix_count = hdrfix_re.subn(
        lambda match: match.group(1) + "ide" + match.group(1),
        next_content,
    )
    stats.client_type += hdrfix_count
    eligibility_re = re.compile(rf"return!1;{ELIGIBILITY_MARKER_PATTERN}")
    next_content, eligibility_count = eligibility_re.subn("", next_content)
    stats.eligibility += eligibility_count
    model_unlock_re = re.compile(r"return!1;" + re.escape(SAND_MODEL_UNLOCK_MARKER))
    next_content, model_unlock_count = model_unlock_re.subn("", next_content)
    stats.eligibility += model_unlock_count
    mem_pro_re = re.compile(r'"(?:enterprise|pro)"\|\|' + re.escape(SAND_MEM_PRO_MARKER))
    next_content, mem_pro_count = mem_pro_re.subn("", next_content)
    stats.eligibility += mem_pro_count
    maxmode_re = re.compile(r"return!0;" + re.escape(SAND_MAXMODE_MARKER))
    next_content, maxmode_count = maxmode_re.subn("", next_content)
    stats.eligibility += maxmode_count

    next_content, route_rb_n = MANAGED_LOCAL_RB_RE.subn(
        lambda match: match.group(1), next_content
    )
    stats.managed_local_route += route_rb_n
    route_count = next_content.count(MANAGED_LOCAL_ROUTE_PATCHED)
    if route_count:
        next_content = next_content.replace(
            MANAGED_LOCAL_ROUTE_PATCHED,
            MANAGED_LOCAL_ROUTE_ORIGINAL,
        )
        stats.managed_local_route += route_count

    next_content, model_rb_n = MODEL_ROUTE_RB_RE.subn(
        lambda match: match.group(1), next_content
    )
    stats.model_route += model_rb_n
    residual_model = next_content.count(SAND_MODEL_ROUTE_MARKER)
    if residual_model:
        next_content = next_content.replace(SAND_MODEL_ROUTE_MARKER, "")
        stats.model_route += residual_model

    next_content, subagent_rb_n = SUBAGENT_ROUTE_RB_RE.subn(
        lambda match: match.group(1), next_content
    )
    stats.sand_rpc += subagent_rb_n
    residual_subagent = next_content.count(SAND_SUBAGENT_ROUTE_MARKER)
    if residual_subagent:
        next_content = next_content.replace(SAND_SUBAGENT_ROUTE_MARKER, "")
        stats.sand_rpc += residual_subagent

    next_content, mode_rb_n = MODE_ROUTE_RB_RE.subn(
        lambda match: match.group(1) + '?"mode-not-supported":', next_content
    )
    stats.sand_rpc += mode_rb_n
    next_content, legacy_mode_rb_n = MODE_ROUTE_LEGACY_RB_RE.subn(
        lambda match: match.group(1) + '?"mode-not-supported":', next_content
    )
    stats.sand_rpc += legacy_mode_rb_n
    residual_mode = next_content.count(SAND_MODE_ROUTE_MARKER)
    if residual_mode:
        next_content = next_content.replace(SAND_MODE_ROUTE_MARKER, "")
        stats.sand_rpc += residual_mode

    next_content, action_rb_n = ACTION_ROUTE_RB_RE.subn(
        lambda match: match.group(1) + '?"action-not-supported":', next_content
    )
    stats.sand_rpc += action_rb_n
    residual_action = next_content.count(SAND_ACTION_ROUTE_MARKER)
    if residual_action:
        next_content = next_content.replace(SAND_ACTION_ROUTE_MARKER, "")
        stats.sand_rpc += residual_action

    next_content, http2_rb_n = HTTP2_GATE_RB_RE.subn(
        lambda match: match.group(1), next_content
    )
    stats.sand_rpc += http2_rb_n
    residual_http2 = next_content.count(SAND_HTTP2_GATE_MARKER)
    if residual_http2:
        next_content = next_content.replace(SAND_HTTP2_GATE_MARKER, "")
        stats.sand_rpc += residual_http2

    next_content, local_model_rb_n = LOCAL_MODEL_RB_RE.subn(
        lambda match: "if(" + match.group(1) + ")" + match.group(2),
        next_content,
    )
    stats.local_model += local_model_rb_n
    residual_local_model = next_content.count(SAND_LOCAL_MODEL_MARKER)
    if residual_local_model:
        next_content = next_content.replace(SAND_LOCAL_MODEL_MARKER, "")
        stats.local_model += residual_local_model

    next_content, runtime_rb_n = LOCAL_RUNTIME_RB_RE.subn(
        lambda match: match.group(1), next_content
    )
    stats.local_runtime_load += runtime_rb_n
    runtime_load_count = next_content.count(LOCAL_RUNTIME_LOAD_PATCHED)
    if runtime_load_count:
        next_content = next_content.replace(
            LOCAL_RUNTIME_LOAD_PATCHED,
            LOCAL_RUNTIME_LOAD_ORIGINAL,
        )
        stats.local_runtime_load += runtime_load_count

    if SAND_MOVE_EXEC_MARKER in next_content:
        next_content, move_exec_rb_n = MOVE_EXEC_RB_RE.subn(
            lambda match: match.group(2),
            next_content,
        )
        stats.move_exec += move_exec_rb_n
        residual_move_exec = next_content.count(SAND_MOVE_EXEC_MARKER)
        if residual_move_exec:
            next_content = next_content.replace(SAND_MOVE_EXEC_MARKER, "")
            stats.move_exec += residual_move_exec

    identity_count = next_content.count(AGENT_HOST_IDENTITY_PATCHED)
    if identity_count:
        next_content = next_content.replace(
            AGENT_HOST_IDENTITY_PATCHED,
            AGENT_HOST_IDENTITY_ORIGINAL,
        )
        stats.agent_host_identity += identity_count

    next_content, direct_count = _strip_direct_stream_injection(next_content)
    stats.direct_stream += direct_count

    # 该正则以变量名开头会全文回溯（47MB 上约 0.7s），marker 不在就没必要跑。
    if SAND_AGENT_HOST_ENABLEMENT_MARKER in next_content:
        next_content, agent_host_count = AGENT_HOST_ENABLEMENT_PATCH_RE.subn(
            lambda match: match.group(2) + match.group(1) + match.group(3),
            next_content,
        )
        stats.agent_host_enablement += agent_host_count

    next_content, mem_snip_count = MEMBERSHIP_SNIPPET_RE.subn("", next_content)
    stats.client_type += mem_snip_count
    residual_marker_re = re.compile(
        r'(["\'])(?:ide|sand|glass|agent)\1((?:/\*SAND[A-Z0-9_]*_V1\*/)+)'
    )

    def _collapse_residual(match: "re.Match[str]") -> str:
        quote = match.group(1)
        first = re.match(r"/\*(SAND[A-Z0-9_]*_V1)\*/", match.group(2)).group(1)
        if "EXISTING" in first:
            value = "sand"
        elif "GLASSFIX" in first:
            value = "glass"
        else:
            value = "ide"
        return f"{quote}{value}{quote}"

    next_content, residual_count = residual_marker_re.subn(_collapse_residual, next_content)
    stats.client_type += residual_count
    next_content = re.sub(
        re.escape(SAND_HDRFIX_RB_PREFIX) + r".+?" + re.escape(SAND_HDRFIX_RB_SUFFIX),
        "",
        next_content,
    )
    next_content = re.sub(
        re.escape(SAND_VERFIX_RB_PREFIX) + r".+?" + re.escape(SAND_VERFIX_RB_SUFFIX),
        "",
        next_content,
    )
    next_content = next_content.replace(SAND_NSFIX_MARKER, "")
    next_content = next_content.replace(SAND_VERFIX_MARKER, "")
    next_content = next_content.replace(SAND_HDRFIX_MARKER, "")
    next_content, ff_n = remove_feature_flag_defaults(next_content)
    stats.feature_flags += ff_n
    next_content, agent_ff_n = remove_agent_runtime_flags(next_content)
    stats.feature_flags += agent_ff_n

    next_content, rpc_n = remove_sand_rpc_lite(next_content)
    stats.sand_rpc += rpc_n
    next_content, ctx_n = remove_ctx_window(next_content)
    stats.ctx_window += ctx_n
    next_content, agent_cfg_n = remove_local_agent_config(next_content)
    stats.local_agent += agent_cfg_n
    next_content, simple_n = remove_simple_replacements(next_content)
    stats.sand_rpc += simple_n

    bridge_n = next_content.count(EXEC_BRIDGE_GET_PATCHED)
    if bridge_n:
        next_content = next_content.replace(
            EXEC_BRIDGE_GET_PATCHED, EXEC_BRIDGE_GET_ORIGINAL
        )
        stats.exec_bridge += bridge_n
    br_n = next_content.count(BR_RESOURCE_GET_PATCHED)
    if br_n:
        next_content = next_content.replace(
            BR_RESOURCE_GET_PATCHED, BR_RESOURCE_GET_ORIGINAL
        )
        stats.exec_bridge += br_n
    return next_content, stats


def _decode_js(data: bytes, path: Path) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SandToolError(f"目标文件不是 UTF-8，拒绝修改：{path}") from exc


def _read_planned_file(path: Path) -> PlannedFile:
    original = path.read_bytes()
    return PlannedFile(
        original=original,
        next_bytes=original,
        mode=stat.S_IMODE(path.stat().st_mode),
    )


def _target_extension_name(layout: CursorLayout, file_path: Path) -> Optional[str]:
    for rel, extension_name in TARGET_SPECS:
        if not extension_name:
            continue
        candidate = layout.app_root.joinpath(*rel.split("/")).resolve()
        if candidate == file_path.resolve():
            return extension_name
    return None


def _update_extension_hashes(
    layout: CursorLayout,
    plan: Dict[Path, PlannedFile],
) -> None:
    changed_extensions: List[Tuple[str, bytes]] = []
    for file_path, planned in plan.items():
        extension_name = _target_extension_name(layout, file_path)
        if extension_name:
            changed_extensions.append((extension_name, planned.next_bytes))
    if not changed_extensions or layout.ext_host_path is None:
        return

    ext_path = layout.ext_host_path
    existing = plan.get(ext_path) or _read_planned_file(ext_path)
    next_content = _decode_js(existing.next_bytes, ext_path)
    original_content = _decode_js(existing.original, ext_path)

    for extension_name, next_main in changed_extensions:
        extension_id = "anysphere." + extension_name
        if f'"{extension_id}"' not in next_content:
            continue
        digest = hashlib.sha256(next_main).hexdigest()
        pattern = re.compile(
            rf'(\"{re.escape(extension_id)}\"\s*:\s*\{{[\s\S]{{0,2400}}?'
            rf'\"main\.js\"\s*:\s*\")[0-9a-f]{{64}}(\")'
        )
        next_content, count = pattern.subn(
            lambda match: match.group(1) + digest + match.group(2),
            next_content,
            count=1,
        )
        if count > 1:
            raise SandToolError(f"{extension_id} 的内嵌 main.js 哈希不唯一")

    if next_content != original_content:
        plan[ext_path] = PlannedFile(
            original=existing.original,
            next_bytes=next_content.encode("utf-8"),
            mode=existing.mode,
        )


def _sync_product_checksums(
    layout: CursorLayout,
    plan: Dict[Path, PlannedFile],
) -> None:
    product_file = _read_planned_file(layout.product_json)
    has_bom = product_file.original.startswith(b"\xef\xbb\xbf")
    try:
        product = json.loads(product_file.original.decode("utf-8-sig"))
    except Exception as exc:
        raise SandToolError("product.json 无法解析，拒绝提交补丁") from exc
    if not isinstance(product, dict):
        raise SandToolError("product.json 顶层必须是对象")
    checksums = product.get("checksums")
    if not isinstance(checksums, dict):
        return

    out_root = (layout.app_root / "out").resolve()
    changed = False
    for key in list(checksums.keys()):
        if not isinstance(key, str):
            continue
        parts = [part for part in re.split(r"[\\/]", key) if part]
        target = out_root.joinpath(*parts).resolve()
        if not _is_within(target, out_root):
            raise SandToolError(f"product.json checksum 路径逃逸：{key}")
        planned = plan.get(target)
        if planned is not None:
            data = planned.next_bytes
        elif target.is_file():
            data = target.read_bytes()
        else:
            continue
        digest = _product_checksum(data)
        if checksums.get(key) != digest:
            checksums[key] = digest
            changed = True

    if not changed:
        return
    text = json.dumps(product, ensure_ascii=False, indent="\t")
    next_bytes = text.encode("utf-8")
    if has_bom:
        next_bytes = b"\xef\xbb\xbf" + next_bytes
    plan[layout.product_json] = PlannedFile(
        original=product_file.original,
        next_bytes=next_bytes,
        mode=product_file.mode,
    )


def _planned_extension_names(
    layout: CursorLayout,
    plan: Mapping[Path, PlannedFile],
) -> Set[str]:
    names: Set[str] = set()
    for file_path in plan:
        extension_name = _target_extension_name(layout, file_path)
        if extension_name:
            names.add(extension_name)
    return names


def _verify_extension_hashes(
    layout: CursorLayout,
    extension_names: Iterable[str],
) -> None:
    names = set(extension_names)
    if layout.ext_host_path is None or not names:
        return
    ext_content = _decode_js(layout.ext_host_path.read_bytes(), layout.ext_host_path)
    for rel, extension_name in TARGET_SPECS:
        if not extension_name or extension_name not in names:
            continue
        main_path = layout.app_root.joinpath(*rel.split("/"))
        if not main_path.is_file():
            continue
        extension_id = "anysphere." + extension_name
        if f'"{extension_id}"' not in ext_content:
            continue
        pattern = re.compile(
            rf'\"{re.escape(extension_id)}\"\s*:\s*\{{[\s\S]{{0,2400}}?'
            rf'\"main\.js\"\s*:\s*\"([0-9a-f]{{64}})\"'
        )
        match = pattern.search(ext_content)
        if not match:
            continue
        expected = hashlib.sha256(main_path.read_bytes()).hexdigest()
        if match.group(1) != expected:
            raise SandToolError(f"{extension_id} 的内嵌哈希校验失败")


def _verify_product_checksums(layout: CursorLayout) -> int:
    product = json.loads(layout.product_json.read_bytes().decode("utf-8-sig"))
    checksums = product.get("checksums") if isinstance(product, dict) else None
    if not isinstance(checksums, dict):
        return 0
    out_root = (layout.app_root / "out").resolve()
    checked = 0
    for key, written in checksums.items():
        if not isinstance(key, str):
            continue
        parts = [part for part in re.split(r"[\\/]", key) if part]
        target = out_root.joinpath(*parts).resolve()
        if not _is_within(target, out_root) or not target.is_file():
            continue
        checked += 1
        if written != _product_checksum(target.read_bytes()):
            raise SandToolError(f"product.json 完整性哈希校验失败：{key}")
    return checked


def _compile_all_markers_re() -> re.Pattern[str]:
    """把所有 SAND marker 合成一条 alternation，单次扫描统一计数。

    原实现对每个 marker 各调一次 str.count，11 个目标文件合计约 130MB，
    17 个 marker 等于扫 2.2GB；合成一条正则后只扫一遍。
    """
    markers = sorted(_ALL_SAND_MARKERS, key=len, reverse=True)
    return re.compile("|".join(re.escape(m) for m in markers))


_ALL_SAND_MARKERS: Tuple[str, ...] = (
    SAND_CLIENT_MARKER,
    SAND_CLIENT_EXISTING_MARKER,
    SAND_HDRFIX_MARKER,
    SAND_GLASSFIX_MARKER,
    SAND_VERFIX_MARKER,
    SAND_NSFIX_MARKER,
    SAND_ELIGIBILITY_MARKER,
    SAND_MANAGED_LOCAL_ROUTE_MARKER,
    SAND_LOCAL_RUNTIME_LOAD_MARKER,
    SAND_MOVE_EXEC_MARKER,
    SAND_MODEL_ROUTE_MARKER,
    SAND_LOCAL_MODEL_MARKER,
    SAND_DIRECT_STREAM_MARKER,
    SAND_AGENT_HOST_ENABLEMENT_MARKER,
    SAND_AGENT_HOST_IDENTITY_MARKER,
    SAND_FEATURE_FLAG_MARKER,
    SAND_AGENT_FLAGS_MARKER,
    SAND_DNS_FIX_MARKER,
    SAND_EXEC_BRIDGE_MARKER,
    SAND_BR_RESOURCE_BRIDGE_MARKER,
    SAND_TASK_TOOL_PROPS_MARKER,
    SAND_SELF_SUMMARY_MARKER,
    SAND_SUBAGENT_ROUTE_MARKER,
    SAND_MODE_ROUTE_MARKER,
    SAND_CTX_WINDOW_MARKER,
    SAND_CTX_WINDOW_END_MARKER,
    SAND_ACTION_ROUTE_MARKER,
    SAND_BG_SUMMARY_MARKER,
    SAND_MODEL_INFO_MARKER,
    SAND_MODEL_INFO_END_MARKER,
    SAND_SUBAGENT_RETRY_MARKER,
    SAND_MAX_RETRIES_MARKER,
    SAND_INTERACTION_ID_MARKER,
    SAND_HTTP2_GATE_MARKER,
)
ALL_MARKERS_RE = _compile_all_markers_re()


def _count_markers(content: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for match in ALL_MARKERS_RE.finditer(content):
        text = match.group(0)
        counts[text] = counts.get(text, 0) + 1
    return counts


_js_cache: Dict[str, Tuple[int, int, str]] = {}


def _read_js_cached(path: Path) -> str:
    """按 (mtime_ns, size) 缓存已解码的 JS 文本。

    单次 install/uninstall 会多次 inspect_status（前置检查 + validate + DNS 复核），
    目标文件合计约 130MB，重复读盘+解码是主要耗时来源。文件被改写后 mtime/size
    变化，缓存自然失效，不会读到旧内容。
    """
    stat_result = path.stat()
    key = _path_key(path)
    cached = _js_cache.get(key)
    if cached is not None and cached[0] == stat_result.st_mtime_ns and cached[1] == stat_result.st_size:
        return cached[2]
    text = _decode_js(path.read_bytes(), path)
    _js_cache[key] = (stat_result.st_mtime_ns, stat_result.st_size, text)
    return text


def invalidate_js_cache() -> None:
    _js_cache.clear()


def inspect_status(layout: CursorLayout) -> PatchStatus:
    client_markers = 0
    eligibility_markers = 0
    legacy_client_markers = 0
    legacy_eligibility_markers = 0
    managed_local_route_markers = 0
    local_runtime_load_markers = 0
    move_exec_markers = 0
    model_route_markers = 0
    local_model_markers = 0
    direct_stream_markers = 0
    agent_host_enablement_markers = 0
    agent_host_identity_markers = 0
    dns_node_markers = 0
    ide_matches = 0
    feature_flag_markers = 0
    exec_bridge_markers = 0
    sand_rpc_markers = 0
    ctx_window_markers = 0
    local_agent_markers = 0
    external_sand_matches = 0
    external_marker_count = 0
    patched_files: List[Path] = []
    for target in layout.target_paths:
        content = _read_js_cached(target)
        marker_counts = _count_markers(content)
        get = marker_counts.get
        client_count = (
            get(SAND_CLIENT_MARKER, 0)
            + get(SAND_CLIENT_EXISTING_MARKER, 0)
            + get(SAND_HDRFIX_MARKER, 0)
            + get(SAND_GLASSFIX_MARKER, 0)
            + get(SAND_VERFIX_MARKER, 0)
            + get(SAND_NSFIX_MARKER, 0)
        )
        eligibility_count = get(SAND_ELIGIBILITY_MARKER, 0)
        managed_local_route_count = get(SAND_MANAGED_LOCAL_ROUTE_MARKER, 0)
        local_runtime_load_count = get(SAND_LOCAL_RUNTIME_LOAD_MARKER, 0)
        move_exec_count = get(SAND_MOVE_EXEC_MARKER, 0)
        model_route_count = get(SAND_MODEL_ROUTE_MARKER, 0)
        local_model_count = get(SAND_LOCAL_MODEL_MARKER, 0)
        direct_stream_count = get(SAND_DIRECT_STREAM_MARKER, 0)
        agent_host_enablement_count = get(SAND_AGENT_HOST_ENABLEMENT_MARKER, 0)
        agent_host_identity_count = get(SAND_AGENT_HOST_IDENTITY_MARKER, 0)
        dns_node_count = get(SAND_DNS_FIX_MARKER, 0)
        feature_flag_count = get(SAND_FEATURE_FLAG_MARKER, 0) + get(
            SAND_AGENT_FLAGS_MARKER, 0
        )
        exec_bridge_count = get(SAND_EXEC_BRIDGE_MARKER, 0) + get(
            SAND_BR_RESOURCE_BRIDGE_MARKER, 0
        )
        sand_rpc_count = (
            get(SAND_TASK_TOOL_PROPS_MARKER, 0)
            + get(SAND_SELF_SUMMARY_MARKER, 0)
            + get(SAND_SUBAGENT_ROUTE_MARKER, 0)
            + get(SAND_MODE_ROUTE_MARKER, 0)
            + get(SAND_ACTION_ROUTE_MARKER, 0)
            + get(SAND_SUBAGENT_RETRY_MARKER, 0)
            + get(SAND_MAX_RETRIES_MARKER, 0)
            + get(SAND_INTERACTION_ID_MARKER, 0)
            + get(SAND_HTTP2_GATE_MARKER, 0)
        )
        ctx_window_count = get(SAND_CTX_WINDOW_MARKER, 0)
        local_agent_count = get(SAND_BG_SUMMARY_MARKER, 0) + get(SAND_MODEL_INFO_MARKER, 0)
        # 旧版 marker 极少出现；先用 in 快速判否，避免对 130MB 跑回溯正则。
        if LEGACY_SAND_CLIENT_MARKER in content:
            legacy_client_count = len(
                re.findall(
                    rf"([\"'])sand\1{LEGACY_CLIENT_MARKER_PATTERN}",
                    content,
                )
            )
        else:
            legacy_client_count = 0
        legacy_eligibility_count = content.count(
            "return!1;" + LEGACY_SAND_ELIGIBILITY_MARKER
        )
        external_marker_count += max(
            0,
            len(re.findall(CLIENT_MARKER_GUARD_PATTERN, content))
            - client_count
            - legacy_client_count,
        )
        external_marker_count += max(
            0,
            len(re.findall(ELIGIBILITY_MARKER_GUARD_PATTERN, content))
            - eligibility_count
            - legacy_eligibility_count,
        )
        if (
            client_count
            + eligibility_count
            + legacy_client_count
            + legacy_eligibility_count
            + managed_local_route_count
            + local_runtime_load_count
            + move_exec_count
            + model_route_count
            + local_model_count
            + direct_stream_count
            + agent_host_enablement_count
            + agent_host_identity_count
            + dns_node_count
            + feature_flag_count
            + exec_bridge_count
            + sand_rpc_count
            + ctx_window_count
            + local_agent_count
        ):
            patched_files.append(target)
        client_markers += client_count
        eligibility_markers += eligibility_count
        legacy_client_markers += legacy_client_count
        legacy_eligibility_markers += legacy_eligibility_count
        managed_local_route_markers += managed_local_route_count
        local_runtime_load_markers += local_runtime_load_count
        move_exec_markers += move_exec_count
        model_route_markers += model_route_count
        local_model_markers += local_model_count
        direct_stream_markers += direct_stream_count
        agent_host_enablement_markers += agent_host_enablement_count
        agent_host_identity_markers += agent_host_identity_count
        dns_node_markers += dns_node_count
        feature_flag_markers += feature_flag_count
        exec_bridge_markers += exec_bridge_count
        sand_rpc_markers += sand_rpc_count
        ctx_window_markers += ctx_window_count
        local_agent_markers += local_agent_count
        for _key, rule in CLIENT_RULES:
            for match in rule.finditer(content):
                if match.group(3) == "sand":
                    external_sand_matches += 1
                else:
                    ide_matches += 1
    dns_diag = diagnose_dns()
    return PatchStatus(
        client_markers=client_markers,
        eligibility_markers=eligibility_markers,
        ide_matches=ide_matches,
        external_sand_matches=external_sand_matches,
        external_marker_count=external_marker_count,
        legacy_client_markers=legacy_client_markers,
        legacy_eligibility_markers=legacy_eligibility_markers,
        patched_files=tuple(patched_files),
        managed_local_route_markers=managed_local_route_markers,
        local_runtime_load_markers=local_runtime_load_markers,
        move_exec_markers=move_exec_markers,
        model_route_markers=model_route_markers,
        local_model_markers=local_model_markers,
        direct_stream_markers=direct_stream_markers,
        agent_host_enablement_markers=agent_host_enablement_markers,
        agent_host_identity_markers=agent_host_identity_markers,
        dns_node_markers=dns_node_markers,
        feature_flag_markers=feature_flag_markers,
        exec_bridge_markers=exec_bridge_markers,
        sand_rpc_markers=sand_rpc_markers,
        ctx_window_markers=ctx_window_markers,
        local_agent_markers=local_agent_markers,
        dns_hosts_installed=bool(dns_diag.get("hosts_installed")),
        dns_hijacked=bool(dns_diag.get("hijacked")),
    )


def _create_backup(
    layout: CursorLayout,
    plan: Mapping[Path, PlannedFile],
    operation: str,
) -> Tuple[Path, Dict[str, object]]:
    app_hash = hashlib.sha256(str(layout.app_root).encode("utf-8")).hexdigest()[:16]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = _config_dir() / "backups" / app_hash / f"{stamp}-{operation}"
    files_dir = backup_dir / "files"
    entries: List[Dict[str, object]] = []
    for path, planned in plan.items():
        try:
            relative = path.resolve().relative_to(layout.app_root.resolve())
        except ValueError as exc:
            raise SandToolError(f"计划文件逃逸出 Cursor app：{path}") from exc
        backup_file = files_dir / relative
        _atomic_write(backup_file, planned.original, planned.mode)
        entries.append(
            {
                "path": relative.as_posix(),
                "originalSha256": _sha256(planned.original),
                "nextSha256": _sha256(planned.next_bytes),
                "mode": planned.mode,
            }
        )
    manifest: Dict[str, object] = {
        "version": 1,
        "toolVersion": TOOL_VERSION,
        "operation": operation,
        "status": "prepared",
        "appRoot": str(layout.app_root),
        "cursorVersion": layout.version,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "files": entries,
    }
    _write_json_atomic(backup_dir / "manifest.json", manifest)
    return backup_dir, manifest


def _update_backup_manifest(
    backup_dir: Path,
    manifest: Dict[str, object],
    status_value: str,
    error: Optional[str] = None,
) -> None:
    manifest["status"] = status_value
    manifest["finishedAt"] = datetime.now(timezone.utc).isoformat()
    if error:
        manifest["error"] = error[:1000]
    _write_json_atomic(backup_dir / "manifest.json", manifest)


def _commit_plan(
    layout: CursorLayout,
    plan: Mapping[Path, PlannedFile],
    operation: str,
    validator,
) -> Tuple[Tuple[Path, ...], Path]:
    if not plan:
        raise SandToolError("内部错误：提交计划为空")
    for path, planned in plan.items():
        if _sha256(path.read_bytes()) != _sha256(planned.original):
            raise SandToolError(f"文件在计划生成后发生变化，已停止操作：{path}")
    backup_dir, manifest = _create_backup(layout, plan, operation)
    attempted: List[Path] = []
    written: List[Path] = []
    try:
        for path, planned in plan.items():
            if _sha256(path.read_bytes()) != _sha256(planned.original):
                raise SandToolError(f"文件在写入前发生变化，已停止操作：{path}")
            attempted.append(path)
            _atomic_write(path, planned.next_bytes, planned.mode)
            written.append(path)
        invalidate_js_cache()
        validator()
        for path, planned in plan.items():
            if _sha256(path.read_bytes()) != _sha256(planned.next_bytes):
                raise SandToolError(f"写入后哈希校验失败：{path}")
        _update_backup_manifest(backup_dir, manifest, "committed")
        return tuple(written), backup_dir
    except (Exception, KeyboardInterrupt) as exc:
        rollback_errors: List[str] = []
        invalidate_js_cache()
        for path in reversed(attempted):
            planned = plan[path]
            try:
                current_hash = _sha256(path.read_bytes())
                original_hash = _sha256(planned.original)
                next_hash = _sha256(planned.next_bytes)
                if current_hash == original_hash:
                    continue
                if current_hash != next_hash:
                    rollback_errors.append(f"{path}: 文件已被外部修改，未覆盖")
                    continue
                _atomic_write(path, planned.original, planned.mode)
            except Exception as rollback_exc:
                rollback_errors.append(f"{path}: {rollback_exc}")
        message = str(exc)
        if rollback_errors:
            message += "; rollback errors: " + " | ".join(rollback_errors)
        try:
            _update_backup_manifest(backup_dir, manifest, "rolled_back", message)
        except Exception:
            pass
        if rollback_errors:
            raise SandToolError(
                "补丁失败且有文件未能自动回滚，请保留备份目录："
                f"{backup_dir}\n{message}"
            ) from exc
        raise


def _windows_close_cursor(layout: CursorLayout) -> int:
    """快速关闭 Cursor：taskkill 强杀进程树，然后轮询等它真正退出（释放单实例锁），
    否则随后的 start 会被判为「已有实例」而直接退出，表现为「打完补丁不重启」。"""
    name = Path(str(layout.executable)).name or "Cursor.exe"
    try:
        subprocess.run(
            ["taskkill", "/F", "/T", "/IM", name],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    # 等进程真正消失（最多 5s，通常 1-2s），确保单实例锁释放。
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            break
        if name.lower() not in (result.stdout or "").lower():
            break
        time.sleep(0.2)
    return 1


def _mac_bundle_pids(layout: CursorLayout) -> List[int]:
    bundle = _find_app_bundle(layout.app_root)
    if bundle is None:
        return []
    contents = (bundle.resolve() / "Contents").resolve()
    pids: List[int] = []
    for pid, executable in _mac_process_paths(strict=True):
        if pid != os.getpid() and _is_within(executable, contents):
            pids.append(pid)
    return pids


def _wait_for_mac_exit(layout: CursorLayout, timeout_seconds: float) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _mac_bundle_pids(layout):
            return True
        time.sleep(0.25)
    return not _mac_bundle_pids(layout)


def _mac_close_cursor(layout: CursorLayout) -> int:
    before = _mac_bundle_pids(layout)
    if not before:
        return 0
    selected_bundle = _find_app_bundle(layout.app_root)
    running_bundles: Dict[str, Path] = {}
    for _pid, executable in _mac_process_paths(strict=True):
        bundle = _bundle_for_executable(executable)
        if bundle is not None:
            running_bundles.setdefault(_path_key(bundle), bundle)
    if selected_bundle is not None and len(running_bundles) == 1:
        osascript = shutil.which("osascript") or "/usr/bin/osascript"
        try:
            subprocess.run(
                [
                    osascript,
                    "-e",
                    'tell application id "com.todesktop.230313mzl4w4u92" to quit',
                ],
                capture_output=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
        if _wait_for_mac_exit(layout, 12):
            return len(before)

    for pid in _mac_bundle_pids(layout):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if _wait_for_mac_exit(layout, 3):
        return len(before)

    for pid in _mac_bundle_pids(layout):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    if not _wait_for_mac_exit(layout, 2):
        raise SandToolError("无法安全关闭所选 Cursor 进程，请手动退出后重试")
    return len(before)


def close_cursor(layout: CursorLayout) -> int:
    if sys.platform == "win32":
        return _windows_close_cursor(layout)
    if sys.platform == "darwin":
        return _mac_close_cursor(layout)
    raise SandToolError("当前仅支持 Windows 和 macOS")


# 启动参数：--classic 让 Cursor 直接进经典 IDE/编辑器窗口，跳过新版 Agents 中枢窗口。
# （官方设置「Open Agents Window on startup / Window Restoration」有会循环回 Agents 窗口的已知 bug，
#  --classic 启动参数是稳定绕过方式。）
CURSOR_START_ARGS: Tuple[str, ...] = ("--classic",)


def start_cursor(layout: CursorLayout) -> bool:
    try:
        if sys.platform == "win32":
            exe = str(layout.executable)
            try:
                # 带 --classic 直接进 IDE；CREATE_NEW_PROCESS_GROUP 让 Cursor 脱离本工具独立存活。
                subprocess.Popen(
                    [exe, *CURSOR_START_ARGS],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    creationflags=0x00000200,  # CREATE_NEW_PROCESS_GROUP
                )
            except OSError:
                # 回退：无参数双击式启动（至少能拉起 Cursor）。
                os.startfile(exe)  # noqa: S606
            return True
        if sys.platform == "darwin":
            bundle = _find_app_bundle(layout.app_root)
            if bundle is None:
                return False
            subprocess.run(
                [shutil.which("open") or "/usr/bin/open", "-a", str(bundle), "--args", *CURSOR_START_ARGS],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
                check=False,
            )
            return True
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def _build_install_plan(
    layout: CursorLayout,
) -> Tuple[Dict[Path, PlannedFile], PatchStats]:
    plan: Dict[Path, PlannedFile] = {}
    total = PatchStats()
    for target in layout.target_paths:
        original = _read_planned_file(target)
        content = _decode_js(original.original, target)
        next_content, stats = apply_patch_to_content(content)
        if target.name in DNS_NODE_TARGETS:
            next_content, dns_n = apply_dns_node_patch(next_content)
            stats.dns_node += dns_n
        # 旧版会在 workbench 注入 fetch 包装，会破坏 ChatService 双向流（Connection Error）。
        # 安装时只剥离旧片段，不再注入。
        if target.name in MEMBERSHIP_TARGET_NAMES:
            stripped, n = MEMBERSHIP_SNIPPET_RE.subn("", next_content)
            if n:
                next_content = stripped
        if next_content != content:
            plan[target] = PlannedFile(
                original=original.original,
                next_bytes=next_content.encode("utf-8"),
                mode=original.mode,
            )
        total.is_glass += stats.is_glass
        total.object_header += stats.object_header
        total.set_header += stats.set_header
        total.eligibility += stats.eligibility
        total.model_unlock += stats.model_unlock
        total.adopted_sand += stats.adopted_sand
        total.migrated_client += stats.migrated_client
        total.migrated_eligibility += stats.migrated_eligibility
        total.managed_local_route += stats.managed_local_route
        total.local_runtime_load += stats.local_runtime_load
        total.move_exec += stats.move_exec
        total.model_route += stats.model_route
        total.local_model += stats.local_model
        total.direct_stream += stats.direct_stream
        total.agent_host_enablement += stats.agent_host_enablement
        total.agent_host_identity += stats.agent_host_identity
        total.dns_node += stats.dns_node
        total.feature_flags += stats.feature_flags
        total.exec_bridge += stats.exec_bridge
        total.sand_rpc += stats.sand_rpc
        total.ctx_window += stats.ctx_window
        total.local_agent += stats.local_agent
    if plan:
        _update_extension_hashes(layout, plan)
        _sync_product_checksums(layout, plan)
    return plan, total


def _build_uninstall_plan(
    layout: CursorLayout,
) -> Tuple[Dict[Path, PlannedFile], RemoveStats]:
    plan: Dict[Path, PlannedFile] = {}
    total = RemoveStats()
    for target in layout.target_paths:
        original = _read_planned_file(target)
        content = _decode_js(original.original, target)
        next_content, stats = remove_patch_from_content(content)
        if target.name in DNS_NODE_TARGETS:
            next_content, dns_n = remove_dns_node_patch(next_content)
            stats.dns_node += dns_n
        if next_content != content:
            plan[target] = PlannedFile(
                original=original.original,
                next_bytes=next_content.encode("utf-8"),
                mode=original.mode,
            )
        total.client_type += stats.client_type
        total.eligibility += stats.eligibility
        total.managed_local_route += stats.managed_local_route
        total.local_runtime_load += stats.local_runtime_load
        total.move_exec += stats.move_exec
        total.model_route += stats.model_route
        total.local_model += stats.local_model
        total.direct_stream += stats.direct_stream
        total.agent_host_enablement += stats.agent_host_enablement
        total.agent_host_identity += stats.agent_host_identity
        total.dns_node += stats.dns_node
        total.feature_flags += stats.feature_flags
        total.exec_bridge += stats.exec_bridge
        total.sand_rpc += stats.sand_rpc
        total.ctx_window += stats.ctx_window
        total.local_agent += stats.local_agent
    if plan:
        _update_extension_hashes(layout, plan)
        _sync_product_checksums(layout, plan)
    return plan, total


def _install_dns_hosts() -> None:
    try:
        install_hosts(TOOL_VERSION)
    except PermissionError as exc:
        raise SandToolError(
            f"无法写入系统 hosts 文件以修复 DNS 劫持：{exc}。"
            "请用管理员权限运行安装脚本。"
        ) from exc
    except OSError as exc:
        raise SandToolError(f"无法写入系统 hosts 文件：{exc}") from exc
    except RuntimeError as exc:
        raise SandToolError(str(exc)) from exc
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["ipconfig", "/flushdns"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _remove_dns_hosts() -> None:
    try:
        if hosts_block_installed():
            remove_hosts()
    except PermissionError as exc:
        raise SandToolError(
            f"无法清理 hosts 中的 Sand DNS 条目：{exc}。"
            "请用管理员权限运行卸载脚本。"
        ) from exc
    except OSError as exc:
        raise SandToolError(f"无法清理 hosts 文件：{exc}") from exc


def _mac_seal(layout: CursorLayout) -> None:
    """macOS：改完 Cursor.app 内文件后清除扩展属性并 ad-hoc 重签名，否则系统会因签名失效拒绝启动。"""
    if sys.platform != "darwin":
        return
    bundle = _find_app_bundle(layout.app_root)
    if bundle is None:
        return
    bundle_str = str(bundle)
    for file, args in (
        ("xattr", ["-cr", bundle_str]),
        ("codesign", ["--force", "--deep", "--sign", "-", bundle_str]),
    ):
        exe = shutil.which(file) or file
        try:
            subprocess.run(
                [exe, *args],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def install(layout: CursorLayout) -> int:
    before = inspect_status(layout)
    if before.external_marker_count:
        raise SandToolError(
            "检测到其他 Sand 模式标记，本脚本不会接管或覆盖它；"
            "请先用原安装方式卸载"
        )
    plan, _stats = _build_install_plan(layout)
    if not plan:
        if before.installed:
            close_cursor(layout)
            _install_dns_hosts()
            start_cursor(layout)
            _drop_legacy_full_loop_key()
            return 0
        raise SandToolError("当前 Cursor 版本未匹配到 Sand 客户端模式规则")

    close_cursor(layout)
    changed_extensions = _planned_extension_names(layout, plan)

    def validate() -> None:
        status = inspect_status(layout)
        if (
            not status.installed
            or status.ide_matches != 0
            or status.external_marker_count != 0
            or status.legacy_client_markers != 0
            or status.legacy_eligibility_markers != 0
        ):
            raise SandToolError(
                "安装后状态校验失败："
                f"markers={status.client_markers + status.eligibility_markers}, "
                f"remainingIde={status.ide_matches}, "
                "remainingLegacy="
                f"{status.legacy_client_markers + status.legacy_eligibility_markers}"
            )
        # Stream 改道不完整时 Cursor 会 Connection Error（Sand 身份只在
        # InferenceService/Stream 被接受）。此处直接判失败并触发回滚，
        # 避免装出一个「能启动但发不出消息」的 Cursor。
        if not status.stream_mode_installed:
            raise SandToolError(
                "安装后 Stream 改道不完整，Cursor 会 Connection Error，已回滚："
                f"identity={status.agent_host_identity_markers} "
                f"enable={status.agent_host_enablement_markers} "
                f"route={status.managed_local_route_markers} "
                f"runtime={status.local_runtime_load_markers} "
                f"move_exec={status.move_exec_markers} "
                f"model={status.model_route_markers} "
                f"local_model={status.local_model_markers} "
                f"direct={status.direct_stream_markers}"
                "（可能是 Cursor 版本锚点变化，请反馈版本号）"
            )
        _verify_extension_hashes(layout, changed_extensions)
        _verify_product_checksums(layout)
        for target in layout.target_paths:
            if not target.is_file():
                continue
            if _has_broken_feature_flags(_read_js_cached(target)):
                raise SandToolError(
                    f"检测到非法 Statsig 补丁残留，Cursor 将无法启动：{target}"
                )

    _commit_plan(layout, plan, "install", validate)
    _install_dns_hosts()
    if not hosts_block_installed():
        raise SandToolError("安装后 DNS hosts 修复未生效，请用管理员权限重试")
    _mac_seal(layout)
    close_cursor(layout)
    start_cursor(layout)
    _drop_legacy_full_loop_key()
    return 0


def uninstall(layout: CursorLayout) -> int:
    before = inspect_status(layout)
    if before.external_marker_count:
        raise SandToolError(
            "检测到无法识别的 Sand 模式标记，拒绝修改；"
            "请先用原安装方式卸载"
        )
    plan, _stats = _build_uninstall_plan(layout)
    if not plan:
        _remove_dns_hosts()
        _drop_legacy_full_loop_key()
        start_cursor(layout)
        return 0

    close_cursor(layout)
    changed_extensions = _planned_extension_names(layout, plan)

    def validate() -> None:
        status = inspect_status(layout)
        if status.installed or status.external_marker_count:
            raise SandToolError(
                "卸载后仍有 Sand marker："
                f"{status.client_markers + status.eligibility_markers}，"
                f"external={status.external_marker_count}"
            )
        _verify_extension_hashes(layout, changed_extensions)
        _verify_product_checksums(layout)

    _commit_plan(layout, plan, "uninstall", validate)
    _remove_dns_hosts()
    _mac_seal(layout)
    close_cursor(layout)
    start_cursor(layout)
    _drop_legacy_full_loop_key()
    return 0


def _permission_hint() -> str:
    script = Path(__file__).resolve()
    if sys.platform == "win32":
        return "请右键以管理员身份打开 PowerShell/终端后重新运行命令。"
    return f'请使用管理员权限重试：sudo python3 "{script}" <命令>'


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Cursor Sand 客户端模式安装/卸载工具（Windows / macOS）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python \"Sand客户端模式安装工具.py\" install\n"
            "  python \"Sand客户端模式安装工具.py\" uninstall\n"
            "  python \"Sand客户端模式安装工具.py\" set-path \"E:\\Development\\IDE\\cursor\"\n"
            "  python3 \"Sand客户端模式安装工具.py\" set-path /Applications/Cursor.app\n"
            "  python \"Sand客户端模式安装工具.py\" set-path auto"
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {TOOL_VERSION}")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("install", help="安装/注入 Sand 客户端模式")
    commands.add_parser("uninstall", help="卸载 Sand 客户端模式")
    set_path = commands.add_parser("set-path", help="设置 Cursor 路径；auto 恢复自动检测")
    set_path.add_argument(
        "path",
        help="Cursor.exe、Cursor.app、resources/app、安装根目录，或 auto",
    )
    return parser


def collect_status_lines() -> List[Tuple[str, str]]:
    try:
        layout = resolve_cursor_layout()
        status = inspect_status(layout)
    except SandToolError as exc:
        return [(str(exc), ANSI_YELLOW)]

    lines: List[Tuple[str, str]] = [
        (f"Cursor {layout.version}：{layout.install_root}", ANSI_BLUE)
    ]
    if status.installed:
        lines.append(("已安装 Sand 客户端模式", ANSI_GREEN))
        if status.stream_mode_installed:
            if status.direct_stream_markers:
                lines.append(
                    (
                        "Stream 改道已启用（3.18.x InferenceService gre/hre → Stream/RunInference）",
                        ANSI_GREEN,
                    )
                )
            else:
                lines.append(
                    ("Stream 改道已启用（3.17.21 agent_host_local_loop → InferenceService）", ANSI_GREEN)
                )
        else:
            hint = (
                "3.18.x 还需 gre/hre + managed-local；"
                "3.17.21 还需 local_loop + move_exec + 478 闸门 + 双白名单绕过"
            )
            lines.append(
                (
                    f"Stream 改道不完整：direct={status.direct_stream_markers} "
                    f"identity={status.agent_host_identity_markers} "
                    f"enable={status.agent_host_enablement_markers} "
                    f"route={status.managed_local_route_markers} "
                    f"runtime={status.local_runtime_load_markers} "
                    f"move_exec={status.move_exec_markers} "
                    f"model={status.model_route_markers} "
                    f"local_model={status.local_model_markers}"
                    f"（{hint}）",
                    ANSI_YELLOW,
                )
            )
    else:
        lines.append(("尚未安装 Sand 客户端模式", ANSI_YELLOW))
    dns_diag = diagnose_dns()
    if dns_diag.get("hijacked"):
        lines.append(
            (
                f"检测到 DNS 劫持/Clash fake-ip：系统解析 {dns_diag.get('system_ip')} "
                f"≠ DoH {dns_diag.get('doh_ip')}",
                ANSI_YELLOW,
            )
        )
    if status.dns_hosts_installed:
        lines.append(("DNS hosts 修复已安装", ANSI_GREEN))
    elif dns_diag.get("hijacked"):
        lines.append(
            (
                "DNS hosts 修复未安装：请用管理员权限运行安装脚本",
                ANSI_RED,
            )
        )
    if status.installed and status.dns_node_markers:
        lines.append((f"Node DNS 注入：{status.dns_node_markers} 处", ANSI_GREEN))
    if status.installed:
        if status.exec_bridge_markers >= 2:
            lines.append(("工具执行兜底（exec-bridge）：已启用", ANSI_GREEN))
        elif status.exec_bridge_markers:
            lines.append(
                (
                    f"工具执行兜底不完整：exec_bridge={status.exec_bridge_markers}（应为 2）",
                    ANSI_YELLOW,
                )
            )
    if status.installed and status.sand_rpc_markers >= 1:
        lines.append(
            (
                f"sand-rpc-lite：Task 注册 + 478 子代理路由已注入（{status.sand_rpc_markers} 处 marker）",
                ANSI_GREEN,
            )
        )
    if status.installed and status.ctx_window_markers >= 2:
        lines.append(
            (
                "上下文窗口分母：按所选 context 参数（如 1M）换算，不再用服务端写死的 300K",
                ANSI_GREEN,
            )
        )
    # 3.18.x 起 modelInfo 由服务端 resolvedModelMetadata 下发，MODEL_INFO 补丁不再需要，
    # 此时只会有 BG_SUMMARY 一个 marker。
    if status.installed and status.local_agent_markers >= 1:
        lines.append(("本地 agent 配置：后台摘要阈值（90%/95%）已注入", ANSI_GREEN))
    if status.installed and status.feature_flag_markers:
        ff_hint = (
            "（Task 子代理：taskToolProps + Roe 客户端开关已注入）"
            if status.sand_rpc_markers >= 1
            else "（原生子代理 / Task 工具受 taskToolProps 限制，暂无法启用）"
        )
        lines.append(
            (
                f"Statsig 开关：{status.feature_flag_markers} 处{ff_hint}",
                ANSI_BLUE,
            )
        )
    if status.external_marker_count:
        lines.append(
            (f"检测到其他工具留下的标记：{status.external_marker_count} 处", ANSI_YELLOW)
        )
    return lines


def status_report_rows(
    layout: CursorLayout, status: PatchStatus, dns: Mapping[str, object]
) -> List[Tuple[str, object]]:
    """与 patch_status.bat（_status_report.py）同顺序、同取值的 key/value 行；
    末尾多一行 external_markers 供 GUI 展示判定依据。"""
    return [
        ("tool_version", TOOL_VERSION),
        ("cursor_version", layout.version),
        ("path", layout.install_root),
        ("patched", status.installed),
        ("stream_mode", status.stream_mode_installed),
        ("move_exec", status.move_exec_markers),
        ("exec_bridge", status.exec_bridge_markers),
        ("sand_rpc", status.sand_rpc_markers),
        ("feature_flags", status.feature_flag_markers),
        ("client_markers", status.client_markers + status.legacy_client_markers),
        ("direct_stream", status.direct_stream_markers),
        ("dns_node", status.dns_node_markers),
        ("dns_hosts", status.dns_hosts_installed),
        ("dns_hijacked", dns.get("hijacked")),
        ("ide_left", status.ide_matches),
        ("files", len(status.patched_files)),
        ("external_markers", status.external_marker_count),
    ]


def status_verdict(status: PatchStatus) -> str:
    """未安装 / 已安装且 Stream 完整 / 已安装但不完整。未安装不再显示成 OK。"""
    if not status.installed:
        return "NOT_INSTALLED"
    if (
        status.stream_mode_installed
        and status.ide_matches == 0
        and status.external_marker_count == 0
    ):
        return "OK"
    return "INCOMPLETE"


def print_banner() -> None:
    print(colorize("使用前请确保当前 Cursor 账号已经获得 Sand 资格", ANSI_YELLOW))
    print(colorize(f"官方领取页面：{SAND_ONBOARDING_URL}", ANSI_BLUE))
    for text, code in collect_status_lines():
        print(colorize(text, code))
    print()


def apply_set_path(value: str) -> int:
    save_cursor_path(value)
    return 0


def print_menu() -> None:
    print(colorize("请选择操作：", ANSI_BOLD))
    print(colorize("  1", ANSI_BOLD, ANSI_GREEN) + ") 安装")
    print(colorize("  2", ANSI_BOLD, ANSI_GREEN) + ") 卸载")
    print(colorize("  3", ANSI_BOLD, ANSI_GREEN) + ") 设置 Cursor 路径")


def prompt_set_path() -> int:
    value = input(colorize("路径> ", ANSI_BLUE)).strip()
    if not value:
        return 0
    with LoadingSpinner("正在设置路径"):
        return apply_set_path(value)


def run_choice(choice: str) -> Optional[int]:
    if choice == "1":
        with LoadingSpinner("正在安装"):
            return install(resolve_cursor_layout())
    if choice == "2":
        with LoadingSpinner("正在卸载"):
            return uninstall(resolve_cursor_layout())
    if choice == "3":
        return prompt_set_path()
    print_warn("无效选项，请输入 1-3。")
    return 0


def interactive_loop() -> int:
    while True:
        print_banner()
        print_menu()
        try:
            choice = input(colorize("请输入编号> ", ANSI_BLUE)).strip()
        except EOFError:
            print()
            return 0
        try:
            run_choice(choice)
        except PermissionError as exc:
            print_error(f"错误：没有写入权限：{exc}")
            print_error(_permission_hint())
        except SandToolError as exc:
            print_error(f"错误：{exc}")
        except KeyboardInterrupt:
            print()
            return 0
        except Exception as exc:
            print_error(f"未预期错误：{exc}")
        print()


def main(argv: Optional[Sequence[str]] = None) -> int:
    _configure_console()
    args_list = list(sys.argv[1:] if argv is None else argv)
    try:
        _platform_name()
        if not args_list:
            return interactive_loop()

        args = build_parser().parse_args(args_list)
        if args.command == "set-path":
            print_banner()
            return apply_set_path(args.path)

        layout = resolve_cursor_layout()
        if args.command == "install":
            code = install(layout)
            print_banner()
            return code
        if args.command == "uninstall":
            code = uninstall(layout)
            print_banner()
            return code
        raise SandToolError(f"未知命令：{args.command}")
    except PermissionError as exc:
        print_error(f"错误：没有写入权限：{exc}")
        print_error(_permission_hint())
        return 3
    except SandToolError as exc:
        print_error(f"错误：{exc}")
        return 2
    except KeyboardInterrupt:
        print_error("操作已取消。")
        return 130
    except Exception as exc:
        print_error(f"未预期错误：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
