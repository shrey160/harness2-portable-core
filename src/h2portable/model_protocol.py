"""Controlled model-protocol adapter for the O-09 pilot (no live calls).

Transport is injected so the protocol rules run against controlled
responses in tests and against a real Meta endpoint only in a separately
authorized live pilot. This module never reads credential files and never
hashes credential contents into identities; profiles are public names.

Pilot profiles (USER_CONFIRMED 28 Oct 2026): executor/improver
``muse-spark-1.3-contributor`` (Muse Spark 1.3 Contributor) with
``transcribe`` for audio. Official endpoint/pricing details remain to be
verified from Meta's primary docs before any live spend; the $20 pilot
cap is enforced here as accumulated reported cost.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

PILOT_EXECUTOR_PROFILE = "muse-spark-1.3-contributor"
PILOT_TRANSCRIBE_PROFILE = "muse-voice-transcribe-1.0"
LIVE_PROFILES = frozenset({PILOT_EXECUTOR_PROFILE})
PILOT_SPEND_CAP_USD = 20.0

Transport = Callable[[dict[str, Any]], dict[str, Any]]
ToolHandler = Callable[[str, dict[str, Any]], Any]


class ProtocolError(RuntimeError):
    """Malformed or unexpected model response (not retried)."""


class BudgetExceeded(ProtocolError):
    """Accumulated reported cost exceeded the pilot cap."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        self.input_tokens += int(raw.get("input_tokens", 0) or 0)
        self.output_tokens += int(raw.get("output_tokens", 0) or 0)
        self.cost_usd += float(raw.get("cost_usd", 0.0) or 0.0)


@dataclass
class ProtocolClient:
    """Minimal tool-loop client over an injected transport."""

    transport: Transport
    executor_profile: str = PILOT_EXECUTOR_PROFILE
    spend_cap_usd: float = PILOT_SPEND_CAP_USD
    max_retries: int = 3
    sleep: Callable[[float], None] = time.sleep
    usage: Usage = field(default_factory=Usage)

    def run(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_handler: ToolHandler | None = None,
        cancel: threading.Event | None = None,
        max_turns: int = 16,
    ) -> dict[str, Any]:
        convo = list(messages)
        for _ in range(max_turns):
            if cancel is not None and cancel.is_set():
                raise ProtocolError("interrupted by caller")
            response = self._call_with_retry({"profile": self.executor_profile,
                                              "messages": convo})
            self.usage.add(response.get("usage"))
            if self.usage.cost_usd > self.spend_cap_usd:
                raise BudgetExceeded(
                    f"pilot spend ${self.usage.cost_usd:.4f} exceeds "
                    f"cap ${self.spend_cap_usd:.2f}")
            tool_calls = response.get("tool_calls")
            if tool_calls:
                if tool_handler is None:
                    raise ProtocolError("model requested tools but no handler given")
                if not isinstance(tool_calls, list):
                    raise ProtocolError("tool_calls must be a list")
                for call in tool_calls:
                    if not isinstance(call, dict) or "name" not in call:
                        raise ProtocolError("tool call missing name")
                    result = tool_handler(str(call["name"]),
                                          dict(call.get("arguments") or {}))
                    convo.append({"role": "tool", "name": call["name"],
                                  "content": result})
                continue
            if not isinstance(response.get("content"), str):
                raise ProtocolError("response missing string content")
            return response
        raise ProtocolError(f"tool loop exceeded {max_turns} turns")

    def _call_with_retry(self, request: dict[str, Any]) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                raw = self.transport(request)
            except TimeoutError:
                raw = {"status": 429}
            if not isinstance(raw, dict):
                raise ProtocolError("transport returned a non-object response")
            status = raw.get("status", 200)
            if status == 429:
                if attempt >= self.max_retries:
                    raise ProtocolError("rate limited; retries exhausted")
                delay = float(raw.get("retry_after", 0.0) or 0.0)
                self.sleep(delay if delay > 0 else min(2.0 ** attempt, 8.0))
                attempt += 1
                continue
            if status != 200:
                raise ProtocolError(f"unexpected status {status!r}")
            if "content" not in raw and "tool_calls" not in raw:
                raise ProtocolError("response has neither content nor tool_calls")
            self.usage.calls += 1
            return raw
