#!/usr/bin/env python3
"""Run a diagnostic command through the VM's local serial console."""
import argparse
import select
import socket
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("command")
p.add_argument("--timeout", type=float, default=15)
p.add_argument("--socket", type=Path, help="Override the VM serial socket for an isolated probe")
a = p.parse_args()
s = socket.socket(socket.AF_UNIX)
s.settimeout(3)
s.connect(str(a.socket or Path(__file__).resolve().parents[1] / "run/console.sock"))
s.sendall(b"\n")
out = b""
deadline = time.monotonic() + 4
while time.monotonic() < deadline:
    if select.select([s], [], [], .3)[0]:
        out += s.recv(65536)
        if b"login:" in out:
            s.sendall(b"root\n")
            out = b""
        if b"# " in out:
            break
marker = "__CONSOLE_" + str(time.time_ns()) + "__"
s.sendall((a.command + "\nprintf '\\n%s\\n' '" + marker + "'\n").encode())
out = b""
deadline = time.monotonic() + a.timeout
while time.monotonic() < deadline:
    if select.select([s], [], [], .25)[0]:
        data = s.recv(65536)
        if not data:
            break
        out += data
        if ("\n" + marker + "\r\n").encode() in out:
            break
print(out.decode(errors="replace"))
s.close()
