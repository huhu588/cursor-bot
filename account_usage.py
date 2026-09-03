"""按账号拉取 Cursor 账期额度与按模型花费（对齐 cursor-byok 账号详情）。

上游：
  - cursor.com/api/dashboard/get-current-period-usage  JSON，账期 API/Auto 分项
  - api2 /auth/full_stripe_profile                       JSON，套餐名
  - api2 DashboardService/GetAggregatedUsageEvents      裸 protobuf，按模型明细

api2 一元接口必须用 Content-Type: application/proto（JSON 会 400/415）。

字段缺失语义（对齐 cursor-byok deriveQuotaPools / spendFromPercent）：
  Cursor 常省略 optional 的 apiSpend/autoSpend 只给百分比。缺失/null 的金额字段返回 None
  而不是 0；apiSpend/autoSpend 缺失但有 percent 与 limit 时按 limit*percent/100 反推，
  并标记 apiSpendDerived/autoSpendDerived=True，否则 UI 会出现「99% · $0.00」。
"""

from __future__ import annotations

import gzip
import json
import struct
import time
from typing import Any, Iterable, List, Optional, Tuple

import requests

from sand_api import PERIOD_USAGE_URL, TIMEOUT, UA, _cookie_headers, _iso_to_ms, _post, parse_token

API2 = "https://api2.cursor.sh"
AGG_PATH = "/aiserver.v1.DashboardService/GetAggregatedUsageEvents"
STRIPE_PATH = "/auth/full_stripe_profile"


def _num(value) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return 0.0
    return 0.0


def _cents(value) -> int:
    n = _num(value)
    if n <= 0:
        return 0
    return int(round(n))


def _num_opt(value) -> Optional[float]:
    """与 _num 相同，但缺失（None）/ 非数值时返回 None，用于区分「没给」和「给了 0」。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return None
    return None


def _cents_opt(value) -> Optional[int]:
    """美分字段：缺失/null/非数值 → None；存在（含 0）→ 非负整数。"""
    n = _num_opt(value)
    if n is None:
        return None
    if n <= 0:
        return 0
    return int(round(n))


def _limit_cents(value) -> int:
    """网页 JSON 的 auto_limit 常是美元（150=$150）；>=1000 视为已经是美分。"""
    n = _num(value)
    if n <= 0:
        return 0
    if n >= 1000:
        return int(round(n))
    return int(round(n * 100))


def _limit_cents_opt(value) -> Optional[int]:
    """_limit_cents 的可选版本：缺失/null → None；存在则按美元/美分启发式换算。"""
    n = _num_opt(value)
    if n is None:
        return None
    return _limit_cents(n)


def _derive_spend(spend: Optional[int], percent: float, limit: Optional[int]) -> Tuple[Optional[int], bool]:
    """spend 缺失且 percent>0 且 limit>0 时按 limit*percent/100 反推；返回 (值, 是否反推)。"""
    if spend is not None:
        return spend, False
    if percent > 0 and limit is not None and limit > 0:
        return int(round(limit * percent / 100.0)), True
    return None, False


def _varint(value: int) -> bytes:
    out = bytearray()
    value = int(value)
    if value < 0:
        value &= (1 << 64) - 1
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _tag(field_no: int, wire: int) -> bytes:
    return _varint((field_no << 3) | wire)


def _encode_varint_field(field_no: int, value: int) -> bytes:
    return _tag(field_no, 0) + _varint(value)


def _decode_varint(buf: bytes, i: int) -> Tuple[int, int]:
    result = 0
    shift = 0
    while i < len(buf):
        byte = buf[i]
        i += 1
        result |= (byte & 0x7F) << shift
        if not (byte & 0x80):
            return result, i
        shift += 7
        if shift > 70:
            break
    return result, i


def _iter_fields(buf: bytes) -> Iterable[Tuple[int, int, Any]]:
    i = 0
    n = len(buf)
    while i < n:
        tag, i = _decode_varint(buf, i)
        field_no = tag >> 3
        wire = tag & 7
        if wire == 0:
            val, i = _decode_varint(buf, i)
            yield field_no, wire, val
        elif wire == 1:
            if i + 8 > n:
                break
            yield field_no, wire, buf[i : i + 8]
            i += 8
        elif wire == 2:
            size, i = _decode_varint(buf, i)
            # 长度越界说明报文被截断，不能把半截 bytes 当成完整字段吐出去。
            if i + size > n:
                break
            yield field_no, wire, buf[i : i + size]
            i += size
        elif wire == 5:
            if i + 4 > n:
                break
            yield field_no, wire, buf[i : i + 4]
            i += 4
        else:
            break


def _as_double(raw: bytes) -> float:
    if len(raw) == 8:
        return struct.unpack("<d", raw)[0]
    return 0.0


def _gunzip(data: bytes) -> bytes:
    if len(data) >= 2 and data[0] == 0x1F and data[1] == 0x8B:
        try:
            return gzip.decompress(data)
        except Exception:
            return data
    return data


def _unary_payloads(raw: bytes) -> List[bytes]:
    body = _gunzip(raw)
    out: List[bytes] = []
    if len(body) >= 5:
        flags = body[0]
        size = struct.unpack(">I", body[1:5])[0]
        if flags & 0x02 == 0 and 0 < size <= len(body) - 5:
            payload = body[5 : 5 + size]
            if flags & 0x01:
                payload = _gunzip(payload)
            out.append(payload)
    out.append(body)
    return out


def _post_unary_proto(jwt: str, path: str, payload: bytes):
    try:
        resp = requests.post(
            API2 + path,
            headers={
                "content-type": "application/proto",
                "connect-protocol-version": "1",
                "authorization": f"Bearer {jwt}",
                "user-agent": "connect-go",
            },
            data=payload,
            timeout=TIMEOUT,
        )
        return resp.status_code, resp.content
    except Exception as exc:
        return 0, str(exc).encode("utf-8", "replace")


def fetch_stripe_profile(jwt: str) -> dict:
    try:
        resp = requests.get(
            API2 + STRIPE_PATH,
            headers={
                "authorization": f"Bearer {jwt}",
                "accept": "application/json",
                "user-agent": UA,
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return {}
        body = resp.json()
    except Exception:
        return {}
    if not isinstance(body, dict):
        return {}
    return {
        "membership": body.get("membershipType") or body.get("membership_type"),
        "subscriptionStatus": body.get("subscriptionStatus") or body.get("subscription_status"),
    }


def fetch_period_usage_json(user_id: str, jwt: str) -> Optional[dict]:
    status, text = _post(PERIOD_USAGE_URL, _cookie_headers(user_id, jwt, origin=True))
    if status != 200:
        return None
    try:
        body = json.loads(text)
    except Exception:
        return None
    if not isinstance(body, dict):
        return None
    plan = body.get("planUsage") or body.get("plan_usage") or {}
    if not isinstance(plan, dict):
        plan = {}
    spend_limit = body.get("spendLimitUsage") or body.get("spend_limit_usage") or {}
    if not isinstance(spend_limit, dict):
        spend_limit = {}
    # 金额字段缺失/null 一律 None（不收成 0），存在且为 0 仍返回 0。
    auto_limit = _limit_cents_opt(plan.get("autoLimit"))
    api_limit = _cents_opt(plan.get("apiLimit"))
    included = _cents_opt(plan.get("includedSpend"))
    bonus = _cents_opt(plan.get("bonusSpend"))
    total_spend = _cents_opt(plan.get("totalSpend"))
    api_percent = _num(plan.get("apiPercentUsed"))
    auto_percent = _num(plan.get("autoPercentUsed"))
    # Cursor 常省略 apiSpend/autoSpend 只给百分比：按 limit*percent/100 反推并打标记。
    api_spend, api_derived = _derive_spend(_cents_opt(plan.get("apiSpend")), api_percent, api_limit)
    auto_spend, auto_derived = _derive_spend(_cents_opt(plan.get("autoSpend")), auto_percent, auto_limit)
    overage_used = _cents_opt(spend_limit.get("individualUsed"))
    overage_limit_usd = _num_opt(spend_limit.get("individualLimit"))
    overage_limit = int(round(overage_limit_usd * 100)) if overage_limit_usd is not None and overage_limit_usd > 0 else (0 if overage_limit_usd is not None else None)
    limit_type = str(spend_limit.get("limitType") or "")
    return {
        "available": True,
        "totalSpendCents": total_spend,
        "includedSpendCents": included,
        "bonusSpendCents": bonus,
        "apiSpendCents": api_spend,
        "autoSpendCents": auto_spend,
        "apiSpendDerived": api_derived,
        "autoSpendDerived": auto_derived,
        "apiLimitCents": api_limit,
        "autoLimitCents": auto_limit,
        "totalPercent": _num(plan.get("totalPercentUsed")),
        "apiPercent": api_percent,
        "autoPercent": auto_percent,
        "displayMessage": body.get("displayMessage") or "",
        "billingCycleStart": body.get("billingCycleStart") or body.get("startDate"),
        "billingCycleEnd": body.get("billingCycleEnd") or body.get("endDate"),
        "overageUsedCents": overage_used,
        "overageLimitCents": overage_limit,
        "overageUnlimited": limit_type.lower() == "unlimited",
        # None 只表示 totalSpend 缺失；存在且为 0 → 0.0。
        "periodSpendUsd": (total_spend / 100.0) if total_spend is not None else None,
    }


def _parse_model_agg(raw: bytes) -> dict:
    item = {
        "modelIntent": "",
        "totalCents": 0.0,
        "inputTokens": 0,
        "outputTokens": 0,
        "cacheWriteTokens": 0,
        "cacheReadTokens": 0,
        "tier": 0,
    }
    for field_no, wire, val in _iter_fields(raw):
        if field_no == 1 and wire == 2:
            item["modelIntent"] = val.decode("utf-8", "replace") if isinstance(val, (bytes, bytearray)) else str(val)
        elif field_no == 2 and wire == 0:
            item["inputTokens"] = int(val)
        elif field_no == 3 and wire == 0:
            item["outputTokens"] = int(val)
        elif field_no == 4 and wire == 0:
            item["cacheWriteTokens"] = int(val)
        elif field_no == 5 and wire == 0:
            item["cacheReadTokens"] = int(val)
        elif field_no == 6 and wire == 1:
            # field6=total_cents(double)；field7 是 request_cost（不是美分），忽略，绝不拿来兜底。
            item["totalCents"] = _as_double(val)
        elif field_no == 8 and wire == 0:
            item["tier"] = int(val)
    return item


def fetch_aggregated_models(jwt: str, start_ms: int, end_ms: int) -> dict:
    payload = _encode_varint_field(2, int(start_ms)) + _encode_varint_field(3, int(end_ms))
    status, raw = _post_unary_proto(jwt, AGG_PATH, payload)
    if status != 200 or not isinstance(raw, (bytes, bytearray)):
        return {"perModel": [], "aggTotalCostCents": 0.0, "inputTokens": 0, "outputTokens": 0}
    models: List[dict] = []
    totals = {"aggTotalCostCents": 0.0, "inputTokens": 0, "outputTokens": 0}
    for blob in _unary_payloads(bytes(raw)):
        parsed_models: List[dict] = []
        parsed_totals = {"aggTotalCostCents": 0.0, "inputTokens": 0, "outputTokens": 0}
        for field_no, wire, val in _iter_fields(blob):
            if field_no == 1 and wire == 2:
                parsed_models.append(_parse_model_agg(val))
            elif field_no == 2 and wire == 0:
                parsed_totals["inputTokens"] = int(val)
            elif field_no == 3 and wire == 0:
                parsed_totals["outputTokens"] = int(val)
            elif field_no == 6 and wire == 1:
                parsed_totals["aggTotalCostCents"] = _as_double(val)
        if parsed_models or parsed_totals["inputTokens"] or parsed_totals["aggTotalCostCents"]:
            models = parsed_models
            totals = parsed_totals
            break
    models.sort(key=lambda m: float(m.get("totalCents") or 0), reverse=True)
    return {
        "perModel": models,
        "aggTotalCostCents": totals["aggTotalCostCents"],
        "inputTokens": totals["inputTokens"],
        "outputTokens": totals["outputTokens"],
    }


def _cycle_ms(period: dict) -> Tuple[int, int]:
    """账期起止毫秒。billingCycleStart/End 支持 ISO 字符串（走 _iso_to_ms）与数字
    （<1e12 视为秒，否则毫秒）；都解析不出时 end 取现在、start 回落到本月 1 号；
    end 早于 start（上游数据异常）时 end 改为现在、保留 start。"""
    now_ms = int(time.time() * 1000)
    start = period.get("billingCycleStart")
    end = period.get("billingCycleEnd")

    def to_ms(value) -> int:
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return 0
            iso = _iso_to_ms(text)
            if iso is not None:
                return int(iso)
            # 纯数字字符串（如 "1756228923913"）按数字处理。
        n = _num(value)
        if n <= 0:
            return 0
        if n < 1e12:
            return int(n * 1000)
        return int(n)

    start_ms = to_ms(start)
    end_ms = to_ms(end)
    if start_ms > 0 and end_ms > 0 and end_ms < start_ms:
        end_ms = now_ms
    if end_ms <= 0:
        end_ms = now_ms
    if start_ms <= 0:
        lt = time.localtime()
        start_ms = int(time.mktime((lt.tm_year, lt.tm_mon, 1, 0, 0, 0, 0, 0, -1)) * 1000)
    return start_ms, end_ms


def fetch_account_usage(token: str, period: Optional[dict] = None) -> dict:
    """账期额度 + 按模型明细。失败字段留空，不把零值当成「没花钱」。

    period：调用方已预取的 fetch_period_usage_json 结果；传入时不再重复请求
    get-current-period-usage（app.account_detail 与 sand_api.get_status 共用一次）。
    """
    user_id, jwt, claims = parse_token(token)
    if period is None:
        period = fetch_period_usage_json(user_id, jwt)
    period = period or {}
    stripe = fetch_stripe_profile(jwt)
    start_ms, end_ms = _cycle_ms(period)
    models = fetch_aggregated_models(jwt, start_ms, end_ms)
    exp = claims.get("exp")
    expired = False
    if isinstance(exp, (int, float)) and exp > 0:
        expired = time.time() >= float(exp)
    return {
        "available": bool(period.get("available")),
        "tokenExpired": expired,
        "tokenExpiresAt": int(exp) if isinstance(exp, (int, float)) and exp else None,
        "membership": stripe.get("membership") or "",
        "subscriptionStatus": stripe.get("subscriptionStatus") or "",
        **period,
        **models,
    }
