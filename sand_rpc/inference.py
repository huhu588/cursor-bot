"""Connect protocol client for aiserver.v1.InferenceService/Stream (sand identity).

Reference: Grok Bot 0.18 sand client (cursor-inference interceptor, sand-client-metadata,
inference_pb message shapes, buildStreamRequest converter).

Sand clients use client-type ``sand``, namespace ``prod``, Connect+proto over HTTP/1.1.
No secrets are embedded; pass ``SAND_TOKEN`` / ``SAND_MACHINE_ID`` via env or ctor args.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import struct
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Iterator, Mapping, Sequence

import httpx

API2 = "https://api2.cursor.sh"
STREAM_PATH = "/aiserver.v1.InferenceService/Stream"

SAND_CLIENT_TYPE = "sand"
SAND_CLIENT_VERSION = "0.18.0"
SAND_BOX_NAMESPACE = "prod"

DEFAULT_MODEL_ID = "grok-4.5"
DEFAULT_PARAMETERS: tuple[tuple[str, str], ...] = (("effort", "high"), ("fast", "true"))
DEFAULT_MAX_MODE = True

ROLE_USER = 1  # INFERENCE_MESSAGE_ROLE_USER

CONNECT_FLAG_END_STREAM = 0x02


# ---------------------------------------------------------------- checksum
def _obfuscate(data: bytearray) -> bytearray:
    last = 165
    for i in range(len(data)):
        data[i] = ((data[i] ^ last) + i % 256) & 255
        last = data[i]
    return data


def create_cursor_checksum(machine_id: str, now_ms: int | None = None) -> str:
    """Build x-cursor-checksum: obfuscated kilosecond timestamp + machine id."""
    now_ms = now_ms if now_ms is not None else int(time.time() * 1000)
    kilos = now_ms // 1_000_000
    raw = bytearray(
        [
            (kilos >> 40) & 255,
            (kilos >> 32) & 255,
            (kilos >> 24) & 255,
            (kilos >> 16) & 255,
            (kilos >> 8) & 255,
            kilos & 255,
        ]
    )
    prefix = base64.urlsafe_b64encode(bytes(_obfuscate(raw))).rstrip(b"=").decode()
    return f"{prefix}{machine_id}"


def _cursor_root() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "Cursor")


def get_machine_id() -> str | None:
    """Read storage.serviceMachineId from local Cursor install, if present."""
    env_mid = os.environ.get("SAND_MACHINE_ID", "").strip()
    if env_mid:
        return env_mid

    machineid_file = os.path.join(_cursor_root(), "machineid")
    if os.path.isfile(machineid_file):
        try:
            mid = open(machineid_file, encoding="utf-8", errors="replace").read().strip()
            if mid:
                return mid
        except OSError:
            pass

    db_path = os.path.join(_cursor_root(), "User", "globalStorage", "state.vscdb")
    if not os.path.isfile(db_path):
        return None
    uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        row = conn.execute(
            "SELECT value FROM ItemTable WHERE key='storage.serviceMachineId'"
        ).fetchone()
        conn.close()
        if row:
            val = row[0]
            return val.decode() if isinstance(val, bytes) else str(val)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- protobuf
def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def _field(field_no: int, wire: int, value: bytes | str | int) -> bytes:
    tag = _varint((field_no << 3) | wire)
    if wire == 0:
        return tag + _varint(int(value))
    if wire == 2:
        if isinstance(value, str):
            value = value.encode("utf-8")
        return tag + _varint(len(value)) + value
    raise ValueError(f"unsupported wire type {wire}")


def build_stream_request(
    text: str,
    model_id: str = DEFAULT_MODEL_ID,
    max_mode: bool = DEFAULT_MAX_MODE,
    parameters: Sequence[tuple[str, str]] = DEFAULT_PARAMETERS,
    built_in_model: bool = True,
    invocation_id: str | None = None,
    conversation_id: str | None = None,
) -> bytes:
    """Serialize aiserver.v1.InferenceStreamRequest (one user text message)."""
    message = _field(1, 0, ROLE_USER) + _field(2, 2, text)

    requested = _field(1, 2, model_id)
    if max_mode:
        requested += _field(2, 0, 1)
    for pid, pval in parameters:
        requested += _field(3, 2, _field(1, 2, pid) + _field(2, 2, str(pval)))
    if built_in_model:
        requested += _field(4, 0, 1)

    req = _field(1, 2, message)
    req += _field(6, 2, invocation_id or str(uuid.uuid4()))
    req += _field(7, 2, requested)
    req += _field(8, 2, conversation_id or str(uuid.uuid4()))
    return req


def envelope(payload: bytes, flags: int = 0) -> bytes:
    """Wrap protobuf payload in a Connect binary envelope."""
    return bytes([flags]) + struct.pack(">I", len(payload)) + payload


# ---------------------------------------------------------------- headers
def sand_headers(
    jwt: str,
    machine_id: str,
    client_version: str = SAND_CLIENT_VERSION,
) -> dict[str, str]:
    request_id = str(uuid.uuid4())
    trace_id = uuid.uuid4().hex
    span_id = uuid.uuid4().hex[:16]
    return {
        "authorization": f"Bearer {jwt}",
        "content-type": "application/connect+proto",
        "connect-protocol-version": "1",
        "x-cursor-checksum": create_cursor_checksum(machine_id),
        "x-cursor-client-type": SAND_CLIENT_TYPE,
        "x-cursor-client-version": client_version,
        "x-sand-box-namespace": SAND_BOX_NAMESPACE,
        "x-ghost-mode": "true",
        "x-request-id": request_id,
        "traceparent": f"00-{trace_id}-{span_id}-01",
    }


# ---------------------------------------------------------------- response parsing
def walk_proto(buf: bytes) -> list[tuple[int, int, int | bytes]]:
    """Generic protobuf walker -> list of (field_no, wire, value|children)."""
    out: list[tuple[int, int, int | bytes]] = []
    i = 0
    n = len(buf)
    while i < n:
        key = 0
        shift = 0
        while True:
            b = buf[i]
            i += 1
            key |= (b & 0x7F) << shift
            if not b & 0x80:
                break
            shift += 7
        field_no, wire = key >> 3, key & 7
        if wire == 0:
            val = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                val |= (b & 0x7F) << shift
                if not b & 0x80:
                    break
                shift += 7
            out.append((field_no, wire, val))
        elif wire == 2:
            ln = 0
            shift = 0
            while True:
                b = buf[i]
                i += 1
                ln |= (b & 0x7F) << shift
                if not b & 0x80:
                    break
                shift += 7
            out.append((field_no, wire, buf[i : i + ln]))
            i += ln
        elif wire == 5:
            out.append((field_no, wire, buf[i : i + 4]))
            i += 4
        elif wire == 1:
            out.append((field_no, wire, buf[i : i + 8]))
            i += 8
        else:
            break
    return out


def _strings(buf: bytes) -> list[str]:
    found: list[str] = []
    for _fno, wire, val in walk_proto(buf):
        if wire == 2 and isinstance(val, bytes):
            try:
                s = val.decode("utf-8")
                if s.isprintable() and s.strip():
                    found.append(s)
            except UnicodeDecodeError:
                found.extend(_strings(val))
    return found


def iter_frames(raw: bytes) -> Iterator[tuple[int, bytes]]:
    """Yield (flags, payload) Connect envelopes from a streamed body."""
    i = 0
    while i + 5 <= len(raw):
        flags = raw[i]
        (length,) = struct.unpack(">I", raw[i + 1 : i + 5])
        i += 5
        payload = raw[i : i + length]
        i += length
        yield flags, payload


def parse_stream(raw: bytes) -> dict[str, object]:
    """Extract text deltas, usage numbers, errors from InferenceStreamResponse frames."""
    text_parts: list[str] = []
    errors: list[str] = []
    usage: list[list[int]] = []
    infos: list[str] = []
    frame_count = 0
    for flags, payload in iter_frames(raw):
        if flags & CONNECT_FLAG_END_STREAM:
            try:
                obj = json.loads(payload.decode("utf-8"))
                if "error" in obj:
                    errors.append(json.dumps(obj["error"], ensure_ascii=False)[:500])
                else:
                    infos.append(json.dumps(obj, ensure_ascii=False)[:300])
            except Exception:
                errors.append(payload.decode("utf-8", "replace")[:500])
            continue
        frame_count += 1
        for fno, wire, val in walk_proto(payload):
            if wire != 2 or not isinstance(val, bytes):
                continue
            if fno == 1:
                text_parts.extend(_strings(val))
            elif fno == 8:
                errors.append(" | ".join(_strings(val)) or f"error(bytes={len(val)})")
            elif fno in (3, 5):
                nums = [v for _f, w, v in walk_proto(val) if w == 0 and isinstance(v, int)]
                usage.append(nums)
            elif fno == 4:
                infos.append(" | ".join(_strings(val))[:300])
    return {
        "frames": frame_count,
        "text": "".join(text_parts),
        "errors": errors,
        "usage": usage,
        "infos": infos,
    }


@dataclass
class InferenceStreamResult:
    frames: int
    text: str
    errors: list[str] = field(default_factory=list)
    usage: list[list[int]] = field(default_factory=list)
    infos: list[str] = field(default_factory=list)
    http_status: int = 0
    resp_headers: Mapping[str, str] = field(default_factory=dict)
    resp_bytes: int = 0

    @classmethod
    def from_parse(cls, parsed: dict[str, object], **extra: object) -> InferenceStreamResult:
        return cls(
            frames=int(parsed.get("frames", 0)),
            text=str(parsed.get("text", "")),
            errors=list(parsed.get("errors") or []),
            usage=list(parsed.get("usage") or []),
            infos=list(parsed.get("infos") or []),
            http_status=int(extra.get("http_status", 0)),
            resp_headers=dict(extra.get("resp_headers") or {}),
            resp_bytes=int(extra.get("resp_bytes", 0)),
        )


class InferenceClient:
    """httpx-based client for InferenceService/Stream with sand headers."""

    def __init__(
        self,
        token: str | None = None,
        machine_id: str | None = None,
        base_url: str = API2,
        client_version: str = SAND_CLIENT_VERSION,
        timeout: float = 90.0,
    ) -> None:
        self.token = (token or os.environ.get("SAND_TOKEN") or "").strip() or None
        self.machine_id = (machine_id or get_machine_id() or "").strip() or None
        self.base_url = base_url.rstrip("/")
        self.client_version = client_version
        self.timeout = timeout

    def _require_credentials(self) -> tuple[str, str]:
        if not self.token:
            raise ValueError("missing token: pass token= or set SAND_TOKEN")
        if not self.machine_id:
            raise ValueError("missing machine_id: pass machine_id=, set SAND_MACHINE_ID, or install Cursor")
        return self.token, self.machine_id

    def stream(
        self,
        prompt: str,
        *,
        model_id: str = DEFAULT_MODEL_ID,
        max_mode: bool = DEFAULT_MAX_MODE,
        parameters: Sequence[tuple[str, str]] = DEFAULT_PARAMETERS,
        built_in_model: bool = True,
        invocation_id: str | None = None,
        conversation_id: str | None = None,
    ) -> InferenceStreamResult:
        """POST InferenceService/Stream and return parsed Connect frames."""
        jwt, machine_id = self._require_credentials()
        headers = sand_headers(jwt, machine_id, self.client_version)
        body = envelope(
            build_stream_request(
                prompt,
                model_id=model_id,
                max_mode=max_mode,
                parameters=parameters,
                built_in_model=built_in_model,
                invocation_id=invocation_id,
                conversation_id=conversation_id,
            )
        )
        url = self.base_url + STREAM_PATH
        with httpx.Client(timeout=self.timeout, http2=False) as client:
            with client.stream("POST", url, headers=headers, content=body) as resp:
                raw = b"".join(resp.iter_bytes())
                parsed = parse_stream(raw)
                result = InferenceStreamResult.from_parse(
                    parsed,
                    http_status=resp.status_code,
                    resp_headers=dict(resp.headers),
                    resp_bytes=len(raw),
                )
                if resp.status_code != 200:
                    try:
                        result.errors.append(
                            json.dumps(json.loads(raw.decode("utf-8")), ensure_ascii=False)[:800]
                        )
                    except Exception:
                        result.errors.append(raw.decode("utf-8", "replace")[:800])
                return result


class FrameBridge:
    """Stub documenting AgentService/Run ↔ InferenceStream proto re-encoding.

    managed-local agent-host speaks Connect bidi ``AgentService/Run``; sand quota
    is accepted on ``InferenceService/Stream``. A future local bridge would:

    * ``agent_run_to_inference_request`` — AgentRunRequest frames → InferenceStreamRequest
    * ``inference_response_to_agent_run`` — InferenceStreamResponse → AgentRunResponse

    Not implemented here; sand-rpc-lite keeps managed-local and uses this module as
    the Python reference for wire-format helpers until a bridge is wired in-process.
    """

    def agent_run_to_inference_request(self, agent_payload: bytes) -> bytes:
        raise NotImplementedError(
            "FrameBridge stub: AgentService/Run → InferenceStreamRequest not implemented"
        )

    def inference_response_to_agent_run(self, inference_payload: bytes) -> bytes:
        raise NotImplementedError(
            "FrameBridge stub: InferenceStreamResponse → AgentRunResponse not implemented"
        )
