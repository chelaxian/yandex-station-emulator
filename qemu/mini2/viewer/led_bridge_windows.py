#!/usr/bin/env python3
"""Windows LED bridge: guest LED agent → viewer panel.

On macOS the fake LED sysfs is a 9p share that the host polls directly.
Windows QEMU has no 9p, so the guest pushes "name brightness" lines plus
"status {json}" over TCP to this bridge (it connects to 10.0.2.2:19095).
The bridge keeps the last values, decodes the ring/clock exactly like
led_bridge.py and POSTs snapshots to the viewer SSE stream.
"""
from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
RUN = STAND / "run"
LISTEN = ("127.0.0.1", 19095)
VIEWER = "http://127.0.0.1:8765/api/event"
MIN_POST_INTERVAL = 0.5

DIGIT_MAP = {
    frozenset("ABCDEF"): "0",
    frozenset("BC"): "1",
    frozenset("ABDEG"): "2",
    frozenset("ABCDG"): "3",
    frozenset("BCFG"): "4",
    frozenset("ACDFG"): "5",
    frozenset("ACDEFG"): "6",
    frozenset("ABC"): "7",
    frozenset("ABCDEFG"): "8",
    frozenset("ABCDFG"): "9",
    frozenset("G"): "-",
    frozenset(): " ",
}

_values: dict[str, int] = {}
_status_json: str = ""
_lock = threading.Lock()
_dirty = threading.Event()


def post(payload: dict) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode()
    req = urllib.request.Request(
        VIEWER, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        urllib.request.urlopen(req, timeout=1.5).read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def bri(name: str) -> int:
    return max(0, min(255, _values.get(name, 0)))


def decode_digit(pos: int) -> str:
    on = [s for s in "ABCDEFG" if bri(f"mini2:white:clock{s}{pos}") > 8]
    return DIGIT_MAP.get(frozenset(on), "?")


def decode_clock() -> tuple[str, bool]:
    d1, d2, d3, d4 = (decode_digit(i) for i in (1, 2, 3, 4))
    colon = (
        bri("mini2:white:clockPLUS1") > 8
        or bri("mini2:white:clockPLUS2") > 8
    )
    degree = bri("mini2:white:clockDEGREE") > 8
    mid = ":" if colon else " "
    text = f"{d1}{d2}{mid}{d3}{d4}".replace(" ", "")
    if len(text) < 4:
        text = f"{d1}{d2}:{d3}{d4}"
    else:
        text = f"{d1}{d2}{mid}{d3}{d4}"
    return text, degree


def snapshot() -> dict:
    ring = []
    for i in range(1, 7):
        r = bri(f"mini2:red:ring{i}")
        g = bri(f"mini2:green:ring{i}")
        b = bri(f"mini2:blue:ring{i}")
        ring.append(f"#{r:02x}{g:02x}{b:02x}")

    segs = {
        name.split("clock", 1)[-1]: v
        for name, v in _values.items()
        if name.startswith("mini2:white:clock")
    }
    clock, degree = decode_clock()
    avg = sum(int(c[i : i + 2], 16) for c in ring for i in (1, 3, 5)) / (6 * 3)
    if avg < 4:
        ui = "idle"
    else:
        rs = [int(c[1:3], 16) for c in ring]
        gs = [int(c[3:5], 16) for c in ring]
        bs = [int(c[5:7], 16) for c in ring]
        if sum(bs) > sum(rs) + sum(gs):
            ui = "listen"
        elif sum(gs) > sum(rs):
            ui = "speak"
        elif sum(rs) > 80 and sum(gs) > 60:
            ui = "think"
        else:
            ui = "listen"
    return {
        "state": "hw",
        "ui": ui,
        "ring": ring,
        "segs": segs,
        "clock": clock,
        "degree": degree,
        "message": f"leds avg={avg:.0f}",
    }


def persist_status() -> None:
    global _status_json
    with _lock:
        payload = _status_json
    if not payload:
        return
    try:
        RUN.mkdir(parents=True, exist_ok=True)
        (RUN / ".firmware-status.json").write_text(payload)
    except OSError:
        pass


def accept_loop() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(LISTEN)
    srv.listen(4)
    print(f"led bridge TCP → {LISTEN[0]}:{LISTEN[1]}", flush=True)
    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            time.sleep(0.5)
            continue
        threading.Thread(target=client_loop, args=(conn,), daemon=True).start()


def client_loop(conn: socket.socket) -> None:
    buf = b""
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                handle_line(line.decode("utf-8", errors="replace").strip())
    except OSError:
        return


def handle_line(line: str) -> None:
    if not line or line == ".":
        _dirty.set()
        return
    if line.startswith("status "):
        global _status_json
        with _lock:
            _status_json = line[7:]
        _dirty.set()
        return
    name, _, value = line.rpartition(" ")
    try:
        v = int(value)
    except ValueError:
        return
    with _lock:
        _values[name] = v
    _dirty.set()


def main() -> int:
    threading.Thread(target=accept_loop, daemon=True).start()
    last_key = None
    last_status = None
    last_post = 0.0
    while True:
        _dirty.wait(timeout=2)
        _dirty.clear()
        try:
            now = time.monotonic()
            if now - last_post < MIN_POST_INTERVAL:
                time.sleep(max(0, MIN_POST_INTERVAL - (now - last_post)))
            with _lock:
                snap = snapshot()
                status = _status_json
            # firmware status must persist whenever it changes, independently
            # of the LED dedup key — the status timestamp advances every 5 s
            if status != last_status:
                last_status = status
                persist_status()
            key = json.dumps(snap, sort_keys=True)
            if key != last_key:
                # only commit last_key after a successful post, so a failed
                # POST (viewer down) is retried on the next snapshot
                if post(snap):
                    last_key = key
                    last_post = time.monotonic()
                else:
                    last_key = None  # retry next round
        except Exception:
            last_key = None  # force a retry next round
            time.sleep(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
