"""LED bridge: guest LED agent (TCP 19095) -> panel state."""
from __future__ import annotations

import json
import socket
import threading

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
    def __init__(self, port: int = 19095):
        self.port = port
        self.values: dict[str, int] = {}
        self.status = ""
        self.lock = threading.Lock()
        self.error = ""

    def start(self) -> None:
        threading.Thread(target=self._accept, daemon=True).start()

    def reset(self) -> None:
        with self.lock:
            self.values.clear()
            self.status = ""

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
            return
        name, _, value = line.rpartition(" ")
        try:
            v = int(value)
        except ValueError:
            return
        with self.lock:
            self.values[name] = v

    def _bri(self, name: str, values: dict[str, int]) -> int:
        return max(0, min(255, values.get(name, 0)))

    def _digit(self, pos: int, values: dict[str, int]) -> str:
        on = [s for s in "ABCDEFG" if self._bri(f"mini2:white:clock{s}{pos}", values) > 8]
        return DIGIT_MAP.get(frozenset(on), "?")

    def snapshot(self) -> dict:
        with self.lock:
            values = dict(self.values)
            status = self.status
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
            "connected": bool(values),
            "error": self.error,
            "ui": ui,
            "ring": ring,
            "clock": clock,
            "firmware": fw,
        }
