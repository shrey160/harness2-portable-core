"""Command line entry point for foreground portable jobs."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .jobs import JobError, read_job, run_job, stop_job


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise JobError(message)


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="h2portable", description="Run and inspect foreground task jobs")
    commands = parser.add_subparsers(dest="action", required=True)
    run = commands.add_parser("run", help="run a foreground job")
    run.add_argument("--id", required=True)
    run.add_argument("--store", required=True)
    run.add_argument("--backend", required=True, choices=("local", "docker"))
    run.add_argument("--image")
    run.add_argument("--workspace", required=True)
    run.add_argument("--timeout", required=True, type=float)
    run.add_argument("command", nargs=argparse.REMAINDER, help="argv after --")
    for action in ("status", "stop"):
        sub = commands.add_parser(action, help=f"{action} a job")
        sub.add_argument("--id", required=True)
        sub.add_argument("--store", required=True)
    return parser


def _exit_status(state: dict[str, Any]) -> int:
    return {"completed": 0, "failed": 1, "timed_out": 124,
            "cancelled": 130, "interrupted": 125, "running": 0}.get(state.get("status"), 1)


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.action == "run":
            command = list(args.command)
            if command and command[0] == "--":
                command.pop(0)
            state = run_job(args.id, args.store, args.backend, args.workspace,
                            args.timeout, command, args.image)
            print(json.dumps(state, sort_keys=True))
            return _exit_status(state)
        state = (read_job if args.action == "status" else stop_job)(args.id, args.store)
        print(json.dumps(state, sort_keys=True))
        return 0
    except (JobError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
