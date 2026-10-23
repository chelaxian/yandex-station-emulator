#!/usr/bin/env python3
"""Start a command in a new session (macOS-safe setsid)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: daemonize.py <pidfile> <logfile> -- <cmd...>", file=sys.stderr)
        return 2
    pidfile = Path(sys.argv[1])
    logfile = Path(sys.argv[2])
    if sys.argv[3] != "--":
        print("expected -- before command", file=sys.stderr)
        return 2
    cmd = sys.argv[4:]
    logfile.parent.mkdir(parents=True, exist_ok=True)
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    out = open(logfile, "ab", buffering=0)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        cwd=str(Path(cmd[1]).resolve().parent) if cmd[0].endswith("python3") and len(cmd) > 1 else None,
    )
    pidfile.write_text(str(proc.pid))
    print(proc.pid)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
