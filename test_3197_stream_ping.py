"""3.19.7: verify prompt metadata synthesis + optional live Stream ping."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from sand_patch import (
    TOOL_VERSION,
    apply_patch_to_content,
    inspect_status,
    remove_patch_from_content,
    resolve_cursor_layout,
)
from sand_rpc.inference import InferenceClient

CURSOR_4883 = Path(r"D:\GongJu\cursor\resources\app\extensions\cursor-agent-host\dist\4883.js")


def _node_metadata_check(patched: str) -> None:
    node = shutil.which("node")
    if not node:
        print("skip node metadata runtime check")
        return
    import re

    m = re.search(
        r'z=\["anthropic".*?function oe\(e,t\)\{.*?\}(?=var re=|function ue\(|class pe\{)',
        patched,
        re.DOTALL,
    )
    if not m:
        raise AssertionError("4883.js missing oe() block")
    script = (
        m.group(0)
        + ";\n"
        + "const mid='claude-fable-5-1',i=mid.toLowerCase(),r=new Map(),"
        + "a={vendor:i.includes('grok')?'xai':i.includes('gemini')?'gemini':"
        + "i.includes('claude')||i.includes('opus')||i.includes('sonnet')||i.includes('fable')?"
        + "'anthropic':i.includes('gpt')||i.includes('codex')?'openai':'unknown',"
        + "promptVersion:'latest',reasoningEffort:r.get('effort'),"
        + "isGrok45ProductPrompt:i.includes('grok'),"
        + "isGrok46ProductPrompt:i.includes('grok-4.6')||i.includes('grok4.6'),"
        + "isClaude4x:i.includes('claude')||i.includes('opus')||i.includes('sonnet')||i.includes('fable'),"
        + "isFable5:i.includes('fable-5')};"
        + "const meta={promptModelInfo:oe(a,mid)};"
        + "if(!meta.promptModelInfo) throw new Error('oe returned undefined');"
        + "console.log(JSON.stringify({tool:'"
        + TOOL_VERSION
        + "',vendor:meta.promptModelInfo.vendor,model:meta.promptModelInfo.modelName,isFable5:meta.promptModelInfo.isFable5}));"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(script)
        path = Path(fh.name)
    try:
        proc = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        data = json.loads(proc.stdout.strip())
        assert data["vendor"] == "anthropic", data
        assert data["model"] == "claude-fable-5-1", data
        assert data["isFable5"] is True, data
        print("ok node metadata", data)
    finally:
        path.unlink(missing_ok=True)


def _live_stream_ping() -> None:
    try:
        from accounts import AccountStore
    except Exception as exc:
        print("skip live stream:", exc)
        return
    accounts = AccountStore().list()
    if not accounts:
        print("skip live stream: no accounts")
        return
    acc = accounts[0]
    token = acc.get("token") or acc.get("access_token")
    if not token:
        print("skip live stream: account has no token")
        return
    client = InferenceClient(token=token, client_version="3.19.7", timeout=45.0)
    result = client.stream("Reply with exactly: pong", model_id="claude-fable-5-1")
    print(
        "live stream:",
        {
            "http": result.http_status,
            "frames": result.frames,
            "text_len": len(result.text),
            "errors": result.errors[:1],
            "preview": result.text[:120].replace("\n", " "),
        },
    )
    if result.http_status != 200:
        raise AssertionError(f"HTTP {result.http_status}: {result.errors}")
    if result.errors:
        raise AssertionError(result.errors)
    if not result.text.strip():
        raise AssertionError("empty stream response")


def main() -> int:
    print("tool", TOOL_VERSION)
    if not CURSOR_4883.is_file():
        print("skip live 4883: not installed")
        return 0
    src, _ = remove_patch_from_content(CURSOR_4883.read_text(encoding="utf-8", errors="replace"))
    out, stats = apply_patch_to_content(src)
    assert stats.direct_stream == 1, stats
    assert "resolvedModelMetadata:{promptModelInfo:oe(a,mid)}" in out
    assert "resolvedModelMetadata:void 0" not in out
    node = shutil.which("node")
    if node:
        tmp = Path(tempfile.mkdtemp()) / "4883.patched.js"
        tmp.write_text(out, encoding="utf-8")
        proc = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise AssertionError(proc.stderr or proc.stdout)
        print("ok node --check")
    _node_metadata_check(out)
    layout = resolve_cursor_layout()
    st = inspect_status(layout)
    print("status", {"installed": st.installed, "direct": st.direct_stream_markers, "stream_ok": st.stream_mode_installed})
    _live_stream_ping()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
