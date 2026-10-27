"""Bounded live pilot for O-09 (owner-run only, never prints secrets).

Loads META_API_KEY/MODEL_API_KEY from the local .env at runtime, calls the
verified Meta Model API (https://api.meta.ai/v1/chat/completions) with
muse-spark-1.3-contributor, enforces the $20 cap from reported token usage
at verified list prices (Input $1.25/M, Output $4.25/M), and freezes the
response for independent checks. Run from WSL in the project venv.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from h2portable.model_protocol import PILOT_EXECUTOR_PROFILE, PILOT_SPEND_CAP_USD, ProtocolClient


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_dotenv()
    key = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY")
    if not key:
        print(json.dumps({"error": "META_API_KEY/MODEL_API_KEY not set"}))
        return 2

    def transport(request: dict) -> dict:
        body = json.dumps({"model": PILOT_EXECUTOR_PROFILE,
                           "messages": request["messages"]}).encode("utf-8")
        req = urllib.request.Request(
            "https://api.meta.ai/v1/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
                status = resp.status
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            raw = {}
            status = exc.code
            try:
                raw = json.loads(exc.read().decode("utf-8"))
            except Exception:
                pass
        usage = raw.get("usage") or {}
        in_tok = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
        out_tok = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
        choices = raw.get("choices") or []
        content = ""
        tool_calls = None
        if choices:
            msg = choices[0].get("message") or {}
            content = msg.get("content") or ""
            tool_calls = msg.get("tool_calls")
        result: dict = {"status": status,
                        "usage": {"input_tokens": in_tok, "output_tokens": out_tok,
                                  "cost_usd": in_tok * 1.25 / 1e6 + out_tok * 4.25 / 1e6}}
        if tool_calls:
            result["tool_calls"] = tool_calls
        else:
            result["content"] = content
        return result

    client = ProtocolClient(transport=transport)
    out = client.run([{"role": "user",
                       "content": "Reply with exactly: PILOT_OK"}])
    frozen = {"profile": PILOT_EXECUTOR_PROFILE, "content": out.get("content"),
              "usage": {"input_tokens": client.usage.input_tokens,
                        "output_tokens": client.usage.output_tokens,
                        "cost_usd": client.usage.cost_usd, "calls": client.usage.calls},
              "cap_usd": PILOT_SPEND_CAP_USD,
              "independent_check": (out.get("content") or "").strip() == "PILOT_OK"}
    print(json.dumps(frozen, sort_keys=True))
    return 0 if frozen["independent_check"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
