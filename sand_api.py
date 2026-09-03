"""Cursor Grok Bot（agent 客户端）资格查询与领取。

端点（2026 实测）：
  - Bot 额度：POST https://cursor.com/api/dashboard/get-sand-usage-status（会话 cookie，Grok Bot 周期额度）
  - 总额度：GET  https://cursor.com/api/usage-summary（会话 cookie）
  - 资格：POST https://cursor.com/api/dashboard/get-sand-access-status（会话 cookie）
  - teamId：POST https://cursor.com/api/dashboard/get-me（会话 cookie）
  - 领取：个人 POST /api/dashboard/start-sand-trial；团队 POST /api/dashboard/request-sand-team-access
  - 周期消费：POST /api/dashboard/get-current-period-usage（account_usage.fetch_period_usage_json 解析）
  - api2 一元接口只在 account_usage 里用裸 protobuf（JSON 调用会 400），本模块不再请求 api2

鉴权：cursor.com 用会话 cookie（userId::jwt），写操作再加 Origin 过 CSRF。
"""

import base64
import datetime
import json
import re
import time

import requests

# Grok Bot 额度（API 路径仍叫 sand，client-type 需打 agent 补丁才计入 bot 额度）
BOT_USAGE_URL = "https://cursor.com/api/dashboard/get-sand-usage-status"
SAND_USAGE_URL = BOT_USAGE_URL  # 兼容旧名
PERIOD_USAGE_URL = "https://cursor.com/api/dashboard/get-current-period-usage"
ACCESS_STATUS_URL = "https://cursor.com/api/dashboard/get-sand-access-status"
START_TRIAL_URL = "https://cursor.com/api/dashboard/start-sand-trial"
TEAM_ACCESS_URL = "https://cursor.com/api/dashboard/request-sand-team-access"
TEAM_ONBOARD_URL = "https://cursor.com/api/dashboard/update-team-sand-onboarding-completed"
GET_ME_URL = "https://cursor.com/api/dashboard/get-me"
USAGE_SUMMARY_URL = "https://cursor.com/api/usage-summary"
TEAM_SPEND_URL = "https://cursor.com/api/dashboard/get-team-spend"
ORIGIN = "https://cursor.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
TIMEOUT = 20


def _b64url_json(segment: str) -> dict:
    segment = segment.replace("-", "+").replace("_", "/")
    segment += "=" * (-len(segment) % 4)
    return json.loads(base64.b64decode(segment).decode("utf-8", "replace"))


def parse_token(raw: str):
    """把用户粘贴的 token 解析成 (user_id, access_token_jwt, claims)。

    支持两种格式：
      1) 纯 access_token（JWT，形如 eyJ...）；user id 从 JWT 的 sub 里取。
      2) ws token：user_01XXX::eyJ...（WorkosCursorSessionToken，:: 可为 %3A%3A）。
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("空 token")
    text = re.sub(r"^WorkosCursorSessionToken=", "", text, flags=re.I).strip()
    sep = "::" if "::" in text else ("%3A%3A" if "%3A%3A" in text else None)
    pasted_uid = None
    jwt = text
    if sep:
        left, _, right = text.partition(sep)
        pasted_uid = left.strip()
        jwt = right.strip()
    claims: dict = {}
    try:
        claims = _b64url_json(jwt.split(".")[1])
    except Exception:
        claims = {}
    sub = str(claims.get("sub", ""))
    from_sub = sub.split("|")[-1] if sub else ""
    user_id = from_sub if from_sub.startswith("user_") else (pasted_uid or "")
    if not user_id.startswith("user_"):
        raise ValueError("无法解析 user id（既不是 ws token，JWT 里也没有 sub）")
    return user_id, jwt, claims


def _cookie(user_id: str, jwt: str) -> str:
    return f"WorkosCursorSessionToken={user_id}%3A%3A{jwt}"


def _first_not_none(*values):
    """返回第一个不为 None 的值（0 / "" / False 都算有效值，不像 `or` 那样被跳过）。"""
    for value in values:
        if value is not None:
            return value
    return None


def _cookie_headers(user_id: str, jwt: str, origin: bool = False) -> dict:
    headers = {
        "cookie": _cookie(user_id, jwt),
        "content-type": "application/json",
        "accept": "application/json",
        "user-agent": UA,
    }
    if origin:
        headers["origin"] = ORIGIN
    return headers


def _post(url: str, headers: dict, body: str = "{}"):
    try:
        resp = requests.post(url, headers=headers, data=body.encode("utf-8"), timeout=TIMEOUT)
        return resp.status_code, resp.text
    except Exception as exc:
        return 0, str(exc)


def _get(url: str, headers: dict):
    try:
        resp = requests.get(url, headers=headers, timeout=TIMEOUT)
        return resp.status_code, resp.text
    except Exception as exc:
        return 0, str(exc)


def fetch_general_usage(user_id: str, jwt: str):
    """查账号总额度（GET usage-summary，会话 cookie，GET 无需 Origin）。返回套餐与总用量百分比。"""
    headers = {"cookie": _cookie(user_id, jwt), "accept": "application/json", "user-agent": UA}
    status, text = _get(USAGE_SUMMARY_URL, headers)
    if status != 200:
        return None
    try:
        body = json.loads(text)
    except Exception:
        return None
    plan = (body.get("individualUsage") or {}).get("plan") or {}
    return {
        "membership": body.get("membershipType"),
        "totalPercent": plan.get("totalPercentUsed"),
        "unlimited": body.get("isUnlimited"),
    }


def _iso_to_ms(iso):
    """ISO8601（如 2026-08-26T17:22:03.913Z）转毫秒时间戳；失败返回 None。"""
    if not iso:
        return None
    try:
        dt = datetime.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def fetch_usage(user_id: str, jwt: str):
    """查 Grok Bot 额度（get-sand-usage-status）。unlocked=已开通（有非零额度）。"""
    status, text = _post(BOT_USAGE_URL, _cookie_headers(user_id, jwt, origin=True))
    if status != 200:
        return None
    try:
        body = json.loads(text)
    except Exception:
        return None
    included_limit_zero = body.get("includedLimitZero")
    has_non_zero = body.get("hasNonZeroIncludedLimit")
    unlocked = (included_limit_zero is not True) and (has_non_zero is True)
    if included_limit_zero is None and has_non_zero is None:
        unlocked = body.get("hasAvailableUsage") is True
    return {
        "unlocked": unlocked,
        "percent": body.get("usagePercent"),
        "nextReset": body.get("nextResetTimestampUtc"),
        "periodStart": body.get("currentPeriodStart"),
        "plan": body.get("grokPlanLabel"),
    }


def fetch_access(user_id: str, jwt: str):
    # cursor.com 的 dashboard POST 端点即使是读也要 Origin 过 CSRF，否则 403。
    status, text = _post(ACCESS_STATUS_URL, _cookie_headers(user_id, jwt, origin=True))
    if status != 200:
        return None
    try:
        body = json.loads(text)
    except Exception:
        return None
    return {
        "granted": body.get("state") == "SAND_ACCESS_STATE_GRANTED",
        "state": body.get("state"),
        "blockReason": body.get("blockReason"),
    }


def fetch_team_id(user_id: str, jwt: str):
    """返回 (team_id, email)。非团队账号 team_id 为 None。"""
    status, text = _post(GET_ME_URL, _cookie_headers(user_id, jwt, origin=True))
    if status != 200:
        return None, None
    try:
        body = json.loads(text)
    except Exception:
        return None, None
    team_id = body.get("teamId")
    email = body.get("email")
    return (team_id if isinstance(team_id, int) and team_id > 0 else None), email


def _tier_label(billing_tier):
    """把 TEAM_MEMBER_BILLING_TIER_TIER_2000 归一成短档位标签「T2000」。

    注意：这个数字是 Cursor 的档位/信用点口径，**不是美元金额**（usage-summary 里
    同值出现在 plan.limit，与 bonus/total 同单位的信用点）。真正的美元只有 includedSpendCents。
    """
    raw = str(billing_tier or "")
    match = re.search(r"(\d+)\s*$", raw)
    if match:
        return "T" + match.group(1)
    short = raw.replace("TEAM_MEMBER_BILLING_TIER_", "").replace("TIER_", "").strip()
    return short or None


def fetch_team_spend(user_id: str, jwt: str, team_id: int):
    """查团队每个成员的绝对额度：档位($)/已用($)/用量%。返回成员列表；失败返回 None。

    合并后 Grok Bot 用量走 cursor.com 团队账单，body 必须带 teamId，否则 401「Team ID is required」。
    """
    body = json.dumps({"teamId": team_id})
    status, text = _post(TEAM_SPEND_URL, _cookie_headers(user_id, jwt, origin=True), body)
    if status != 200:
        return None
    try:
        rows = json.loads(text).get("teamMemberSpend")
    except Exception:
        return None
    return rows if isinstance(rows, list) else None


def _spend_row_for(rows, email, user_id):
    """在 team-spend 列表里按邮箱（优先）或 userId 匹配当前账号那一行。"""
    if not rows:
        return None
    want = (email or "").strip().lower()
    uid = (user_id or "").strip().lower()
    for row in rows:
        if want and str(row.get("email", "")).strip().lower() == want:
            return row
    for row in rows:
        rid = str(row.get("userId") or row.get("id") or "").strip().lower()
        if uid and rid and (rid == uid or rid.endswith(uid) or uid.endswith(rid)):
            return row
    return None


def _spend_fields(row) -> dict:
    """把一行 team-spend 归一成给 UI 用的绝对额度字段。"""
    if not row:
        return {}
    cents = row.get("includedSpendCents")
    return {
        "billingTier": row.get("billingTier"),
        "tierLabel": _tier_label(row.get("billingTier")),
        "spendUsd": (cents / 100.0) if isinstance(cents, (int, float)) else None,
        "teamPercent": row.get("totalPercentUsed"),
        "autoPercent": row.get("autoPercentUsed"),
        "apiPercent": row.get("apiPercentUsed"),
        "role": row.get("role"),
    }


def start_trial(user_id: str, jwt: str):
    status, text = _post(START_TRIAL_URL, _cookie_headers(user_id, jwt, origin=True))
    if status != 200:
        return "failed", f"HTTP {status}: {text[:160]}"
    low = text.lower()
    if "cardverificationrequired" in low or "card_verification" in low:
        match = re.search(r'"(https://[^"]*(?:checkout|stripe)[^"]*)"', text)
        return "card_required", (match.group(1) if match else "")
    return "activated", ""


def request_team(user_id: str, jwt: str, team_id: int):
    body = json.dumps({"teamId": team_id})
    status, text = _post(TEAM_ACCESS_URL, _cookie_headers(user_id, jwt, origin=True), body)
    if status != 200:
        return "failed", f"HTTP {status}: {text[:160]}"
    # 标记团队 onboarding 完成是幂等辅助调用，失败不影响领取结果。
    _post(TEAM_ONBOARD_URL, _cookie_headers(user_id, jwt, origin=True), body)
    return "team_ok", ""


def get_status(token: str, period=None) -> dict:
    """查询单个账号的 Sand 状态（只读），供 UI 展示。

    period：调用方已预取的 account_usage.fetch_period_usage_json 结果（dict）；传入时不再
    重复请求 get-current-period-usage。为 None 时自行请求一次；请求失败则 period 相关字段为
    None（不再回落重试，避免同一接口重复打一遍）。
    金额字段（apiSpendCents 等）原样透传：None 表示上游缺失，不会被收成 0；
    百分比字段按「team-spend → period → usage-summary」分层取第一个非 None 值，真实 0 不会被当缺失跳过。
    """
    user_id, jwt, claims = parse_token(token)
    usage = fetch_usage(user_id, jwt)
    team_id, email = fetch_team_id(user_id, jwt)
    general = fetch_general_usage(user_id, jwt)
    resolved_email = email or claims.get("email") or user_id
    # 团队账号：从 team-spend 拿绝对额度（档位$/已用$/用量%）；个人号无 teamId 跳过。
    spend = {}
    if team_id is not None:
        rows = fetch_team_spend(user_id, jwt, team_id)
        spend = _spend_fields(_spend_row_for(rows, resolved_email, user_id))
    if period is None:
        try:
            from account_usage import fetch_period_usage_json

            period = fetch_period_usage_json(user_id, jwt)
        except Exception:
            period = None
    if not isinstance(period, dict):
        period = None
    period_spend = period.get("periodSpendUsd") if period else None
    return {
        "email": resolved_email,
        "teamId": team_id,
        "unlocked": usage.get("unlocked") if usage else None,
        "percent": usage.get("percent") if usage else None,
        "nextReset": usage.get("nextReset") if usage else None,
        "periodStart": usage.get("periodStart") if usage else None,
        "periodSpendUsd": period_spend,
        "plan": usage.get("plan") if usage else None,
        "membership": general.get("membership") if general else None,
        "totalPercent": _first_not_none(
            period.get("totalPercent") if period else None,
            general.get("totalPercent") if general else None,
        ),
        "unlimited": general.get("unlimited") if general else None,
        "billingTier": spend.get("billingTier"),
        "tierLabel": spend.get("tierLabel"),
        "spendUsd": spend.get("spendUsd"),
        "teamPercent": spend.get("teamPercent"),
        "autoPercent": _first_not_none(spend.get("autoPercent"), period.get("autoPercent") if period else None),
        "apiPercent": _first_not_none(spend.get("apiPercent"), period.get("apiPercent") if period else None),
        "apiSpendCents": period.get("apiSpendCents") if period else None,
        "autoSpendCents": period.get("autoSpendCents") if period else None,
        "apiSpendDerived": bool(period.get("apiSpendDerived")) if period else None,
        "autoSpendDerived": bool(period.get("autoSpendDerived")) if period else None,
        "apiLimitCents": period.get("apiLimitCents") if period else None,
        "autoLimitCents": period.get("autoLimitCents") if period else None,
        "overageUsedCents": period.get("overageUsedCents") if period else None,
        "overageLimitCents": period.get("overageLimitCents") if period else None,
        "overageUnlimited": period.get("overageUnlimited") if period else None,
        "usageAvailable": bool(period.get("available")) if period else None,
    }


def claim(token: str) -> dict:
    """领取 Sand：已开通短路；能读到 teamId 走团队通道（带 teamId）；否则个人试用；免费号返回需绑卡。"""
    user_id, jwt, claims = parse_token(token)
    # 提前取 teamId + 真实 email（get-me），让每个返回分支都能带上邮箱。
    team_id, me_email = fetch_team_id(user_id, jwt)
    email = me_email or claims.get("email") or user_id
    usage = fetch_usage(user_id, jwt)
    if usage and usage.get("unlocked"):
        return {"outcome": "already", "email": email, "teamId": team_id, "percent": usage.get("percent"), "detail": "已开通"}
    access = fetch_access(user_id, jwt)
    if access and access.get("granted"):
        return {"outcome": "already", "email": email, "teamId": team_id, "detail": "已授予资格"}
    if team_id is not None:
        outcome, detail = request_team(user_id, jwt, team_id)
        return {
            "outcome": "team_ok" if outcome == "team_ok" else "failed",
            "email": email,
            "teamId": team_id,
            "detail": detail or "团队已请求/开通",
        }
    outcome, detail = start_trial(user_id, jwt)
    if outcome == "activated":
        return {"outcome": "activated", "email": email, "detail": "个人已开通"}
    if outcome == "card_required":
        return {"outcome": "card_required", "email": email, "detail": "免费账号需先验证信用卡", "url": detail}
    return {"outcome": "failed", "email": email, "detail": detail}
