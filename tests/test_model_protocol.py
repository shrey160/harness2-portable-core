"""Controlled-response tests for the O-09 model protocol (no live calls)."""

from __future__ import annotations

import threading
import unittest

from h2portable.model_protocol import (
    PILOT_EXECUTOR_PROFILE,
    BudgetExceeded,
    ProtocolClient,
    ProtocolError,
)


def _client(transport, **kwargs):
    kwargs.setdefault("sleep", lambda _s: None)
    return ProtocolClient(transport=transport, **kwargs)


class TestModelProtocol(unittest.TestCase):
    def test_tool_continuation_then_content(self) -> None:
        calls = {"n": 0}

        def transport(req):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"status": 200, "tool_calls": [{"name": "echo", "arguments": {"x": 1}}],
                        "usage": {"input_tokens": 5, "output_tokens": 2, "cost_usd": 0.01}}
            assert req["messages"][-1]["role"] == "tool"
            return {"status": 200, "content": "done",
                    "usage": {"input_tokens": 3, "output_tokens": 1, "cost_usd": 0.01}}

        out = _client(transport).run(
            [{"role": "user", "content": "hi"}],
            tool_handler=lambda name, args: f"{name}:{args['x']}")
        self.assertEqual(out["content"], "done")

    def test_rate_limit_retries_then_succeeds(self) -> None:
        seq = iter([{"status": 429, "retry_after": 0},
                    {"status": 200, "content": "ok"}])
        out = _client(lambda _r: next(seq)).run([{"role": "user", "content": "x"}])
        self.assertEqual(out["content"], "ok")

    def test_rate_limit_exhaustion_fails(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "retries exhausted"):
            _client(lambda _r: {"status": 429}, max_retries=2).run(
                [{"role": "user", "content": "x"}])

    def test_malformed_response_fails_fast(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "neither content"):
            _client(lambda _r: {"status": 200, "junk": True}).run(
                [{"role": "user", "content": "x"}])

    def test_interruption_blocks_call(self) -> None:
        ev = threading.Event(); ev.set()
        with self.assertRaisesRegex(ProtocolError, "interrupted"):
            _client(lambda _r: {"status": 200, "content": "x"}).run(
                [{"role": "user", "content": "x"}], cancel=ev)

    def test_usage_accounting_and_budget_cap(self) -> None:
        c = _client(lambda _r: {"status": 200, "content": "ok",
                                "usage": {"input_tokens": 10, "output_tokens": 5,
                                          "cost_usd": 0.5}},
                    spend_cap_usd=20.0)
        c.run([{"role": "user", "content": "x"}])
        self.assertEqual((c.usage.input_tokens, c.usage.calls), (10, 1))
        self.assertEqual(PILOT_EXECUTOR_PROFILE, "muse-spark-1.3-contributor")
        over = _client(lambda _r: {"status": 200, "content": "ok",
                                   "usage": {"cost_usd": 21.0}}, spend_cap_usd=20.0)
        with self.assertRaises(BudgetExceeded):
            over.run([{"role": "user", "content": "x"}])


if __name__ == "__main__":
    unittest.main()
