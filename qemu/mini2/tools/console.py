#!/usr/bin/env python3
"""Run a diagnostic command through the VM's local serial console.

Windows port: the console chardev is a TCP socket on 127.0.0.1:19096
(Windows QEMU has no AF_UNIX chardev); on macOS/AF_UNIX hosts the unix
socket is still tried first. --socket accepts a path or host:port.
"""
import argparse
import select
import socket
import time
from pathlib import Path

CONSOLE_TCP = ("127.0.0.1", 19096)


def connect(spec: str | None) -> socket.socket:
    if spec and ":" in spec and not spec.startswith("\\\\"):
        host, _, port = spec.rpartition(":")
        s = socket.create_connection((host or "127.0.0.1", int(port)), timeout=3)
        return s
    if spec:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(spec)
        return s
    unix = Path(__file__).resolve().parents[1] / "run" / "console.sock"
    if hasattr(socket, "AF_UNIX"):
        try:
            s = socket.socket(socket.AF_UNIX)
            s.settimeout(3)
            s.connect(str(unix))
            return s
        except OSError:
            pass
    s = socket.create_connection(CONSOLE_TCP, timeout=3)
    return s


p = argparse.ArgumentParser()
p.add_argument("command")
p.add_argument("--timeout", type=float, default=15)
p.add_argument("--socket", help="Override the VM serial socket (path or host:port)")
a = p.parse_args()
s = connect(a.socket)
s.settimeout(3)
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
