"""LED bridge: guest LED agent (TCP 19095) -> panel state.

The guest pushes its fake sysfs values every ~0.2 s and the firmware status
every ~5 s. Both are kept with a host-side receive timestamp: when the guest
stops sending (QEMU stopped, guest hung, agent died) the panel must show
"no data" instead of the last known state forever.
"""
from __future__ import annotations

import json
import socket
import threading
import time

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


class Bridge:
    def __init__(self, port: int = 19095, status_ttl: float = 20.0, led_ttl: float = 5.0):
        self.port = port
        self.status_ttl = status_ttl
        self.led_ttl = led_ttl
        self.values: dict[str, int] = {}
        self.status = ""
        self.status_at = 0.0
        self.values_at = 0.0
        self.lock = threading.Lock()
        self.error = ""

    def start(self) -> None:
        threading.Thread(target=self._accept, daemon=True).start()

    def reset(self) -> None:
        with self.lock:
            self.values.clear()
            self.status = ""
            self.status_at = 0.0
            self.values_at = 0.0

    def _accept(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(("127.0.0.1", self.port))
            srv.listen(4)
        except OSError as e:
            self.error = str(e)
            return
        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                continue
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn: socket.socket) -> None:
        buf = b""
        try:
            while True:
                data = conn.recv(8192)
                if not data:
                    return
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    self._line(line.decode("utf-8", "replace").strip())
        except OSError:
            return

    def _line(self, line: str) -> None:
        if not line or line == ".":
            return
        if line.startswith("status "):
            with self.lock:
                self.status = line[7:]
                self.status_at = time.monotonic()
            return
        name, _, value = line.rpartition(" ")
        try:
            v = int(value)
        except ValueError:
            return
        with self.lock:
            self.values[name] = v
            self.values_at = time.monotonic()

    def _bri(self, name: str, values: dict[str, int]) -> int:
        return max(0, min(255, values.get(name, 0)))

    def _digit(self, pos: int, values: dict[str, int]) -> str:
        on = [s for s in "ABCDEFG" if self._bri(f"mini2:white:clock{s}{pos}", values) > 8]
        return DIGIT_MAP.get(frozenset(on), "?")

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self.lock:
            status = self.status
            status_at = self.status_at
            values_at = self.values_at
            values = dict(self.values)
        status_age = now - status_at if status_at else None
        values_age = now - values_at if values_at else None
        status_fresh = status_age is not None and status_age <= self.status_ttl
        led_fresh = values_age is not None and values_age <= self.led_ttl
        if not status_fresh:
            status = ""
        if not led_fresh:
            values = {}

        ring = []
        for i in range(1, 7):
            r = self._bri(f"mini2:red:ring{i}", values)
            g = self._bri(f"mini2:green:ring{i}", values)
            b = self._bri(f"mini2:blue:ring{i}", values)
            ring.append(f"#{r:02x}{g:02x}{b:02x}")
        d = [self._digit(i, values) for i in (1, 2, 3, 4)]
        colon = self._bri("mini2:white:clockPLUS1", values) > 8 or self._bri("mini2:white:clockPLUS2", values) > 8
        clock = f"{d[0]}{d[1]}{':' if colon else ' '}{d[2]}{d[3]}"
        avg = sum(int(c[i : i + 2], 16) for c in ring for i in (1, 3, 5)) / 18
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
        fw = {}
        if status:
            try:
                fw = json.loads(status)
            except ValueError:
                fw = {}
        return {
            "connected": led_fresh or status_fresh,
            "error": self.error,
            "ui": ui,
            "ring": ring,
            "clock": clock,
            "firmware": fw,
            "firmware_fresh": status_fresh,
            "firmware_age": round(status_age, 1) if status_age is not None else None,
            "led_fresh": led_fresh,
            "led_age": round(values_age, 1) if values_age is not None else None,
        }
