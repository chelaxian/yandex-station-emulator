"""Run one diagnostic command through the VM's TCP serial console."""
from __future__ import annotations

import argparse
import select
import socket
import time


def run(command: str, port: int = 19096, timeout: float = 15) -> str:
    s = socket.create_connection(("127.0.0.1", port), timeout=3)
    s.settimeout(3)
    s.sendall(b"\n")
    out = b""
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        if select.select([s], [], [], 0.3)[0]:
            out += s.recv(65536)
            if b"login:" in out:
                s.sendall(b"root\n")
                out = b""
            if b"# " in out:
                break
    marker = "__CONSOLE_" + str(time.time_ns()) + "__"
    s.sendall((command + "\nprintf '\\n%s\\n' '" + marker + "'\n").encode())
    out = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if select.select([s], [], [], 0.25)[0]:
            data = s.recv(65536)
            if not data:
                break
            out += data
            if ("\n" + marker + "\r\n").encode() in out:
                break
    s.close()
    return out.decode(errors="replace")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command")
    ap.add_argument("--port", type=int, default=19096)
    ap.add_argument("--timeout", type=float, default=15)
    a = ap.parse_args()
    print(run(a.command, a.port, a.timeout).rstrip())


if __name__ == "__main__":
    main()
