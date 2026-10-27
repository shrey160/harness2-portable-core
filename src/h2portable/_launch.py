"""Wait for durable ownership registration before executing a local payload."""
import os
import sys

if sys.stdin.buffer.read(1) != b"1":
    raise SystemExit(125)
with open(os.devnull, "rb") as stream:
    os.dup2(stream.fileno(), 0)
try:
    os.execvp(sys.argv[1], sys.argv[1:])
except OSError as exc:
    print(f"could not launch worker: {exc}", file=sys.stderr)
    raise SystemExit(127)

