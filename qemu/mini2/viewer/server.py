#!/usr/bin/env python3
"""Mini 2 viewer — UI + SSE + QEMU control.

  python3 server.py          # http://127.0.0.1:8765/
  POST /api/qemu {"action":"boot"|"stop"|"reboot"|"clear"}
"""
from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
STAND = ROOT.parent
START_SH = STAND / "start.sh"
RUN = STAND / "run"
LED_SYSFS = STAND / "led_sysfs"
MK_LEDS = STAND / "tools" / "mk_led_sysfs.py"
ALICE_LEDS = STAND / "tools" / "alice_leds.py"
LED_BRIDGE = ROOT / "led_bridge.py"
PATTERNS = (
    STAND
    / "rootfs_files"
    / "system"
    / "vendor"
    / "quasar"
    / "ledpatterns"
    / "oknix"
)
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))

_lock = threading.Lock()
_clients: dict[str, queue.Queue] = {}
_history: list[dict[str, Any]] = []
HISTORY_MAX = 120
_ctl_lock = threading.Lock()
_busy = False
_alice_proc: subprocess.Popen | None = None
_bridge_proc: subprocess.Popen | None = None

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
}


def broadcast(event: dict[str, Any]) -> None:
    event = dict(event)
    event.setdefault("ts", time.time())
    with _lock:
        _history.append(event)
        if len(_history) > HISTORY_MAX:
            del _history[: len(_history) - HISTORY_MAX]
        dead: list[str] = []
        for cid, q in _clients.items():
            try:
                q.put_nowait(event)
            except queue.Full:
                # переполнен — выкидываем старое и пробуем ещё раз
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    dead.append(cid)
            except Exception:
                dead.append(cid)
        for cid in dead:
            _clients.pop(cid, None)


def _read_pid(name: str) -> int | None:
    fp = RUN / name
    try:
        return int(fp.read_text().strip())
    except Exception:
        return None


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def qemu_status() -> dict[str, Any]:
    qemu_pid = _read_pid("qemu.pid")
    start_pid = _read_pid("start.pid")
    tail_pid = _read_pid("console_tail.pid")
    # Match this stand's serial socket; isolated probe VMs have their own socket.
    up = _alive(qemu_pid)
    if not up:
        try:
            r = subprocess.run(
                ["pgrep", "-f", "path=" + str(RUN / "console.sock")],
                capture_output=True,
                text=True,
                timeout=2,
            )
            up = r.returncode == 0 and bool(r.stdout.strip())
            if up and r.stdout.strip():
                qemu_pid = int(r.stdout.strip().splitlines()[0])
        except Exception:
            pass
    return {
        "up": up,
        "busy": _busy,
        "qemu_pid": qemu_pid if _alive(qemu_pid) else None,
        "start_pid": start_pid if _alive(start_pid) else None,
        "tail_pid": tail_pid if _alive(tail_pid) else None,
        "console": str(RUN / "console.log"),
    }


def _kill_pid(pid: int | None, sig: int = signal.SIGTERM) -> None:
    if not pid:
        return
    try:
        os.kill(pid, sig)
    except OSError:
        pass


def _pkill_patterns() -> None:
    for pat in (
        "path=" + str(RUN / "console.sock"),
        str(ROOT / "console_tail.py"),
        str(START_SH),
    ):
        try:
            subprocess.run(
                ["pkill", "-f", pat],
                capture_output=True,
                timeout=3,
            )
        except Exception:
            pass


def ensure_led_sysfs() -> None:
    if not any(LED_SYSFS.glob("mini2:*")):
        subprocess.run([sys.executable, str(MK_LEDS), "--out", str(LED_SYSFS)], check=False)


def ensure_led_bridge() -> None:
    global _bridge_proc
    ensure_led_sysfs()
    if _bridge_proc and _bridge_proc.poll() is None:
        return
    if _alive(_read_pid("led_bridge.pid")):
        return
    RUN.mkdir(parents=True, exist_ok=True)
    log = open(RUN / "led_bridge.log", "ab", buffering=0)
    _bridge_proc = subprocess.Popen(
        [sys.executable, str(LED_BRIDGE), str(LED_SYSFS)],
        cwd=str(STAND),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (RUN / "led_bridge.pid").write_text(str(_bridge_proc.pid))


def stop_alice_leds() -> None:
    global _alice_proc
    pid = _alice_proc.pid if _alice_proc else _read_pid("alice_leds.pid")
    _kill_pid(pid)
    _alice_proc = None
    try:
        subprocess.run(
            ["pkill", "-f", f"{ALICE_LEDS}"],
            capture_output=True,
            timeout=2,
        )
    except Exception:
        pass
    time.sleep(0.15)


def start_alice_leds(mode: str) -> dict[str, Any]:
    """Virtual Alice writes LED sysfs (как led_util/maind)."""
    global _alice_proc
    if (STAND / "mini2-backup.ext4").exists():
        return {"ok": False, "error": "Подсветкой управляет настоящая прошивка; демонстрация отключена."}
    ensure_led_sysfs()
    ensure_led_bridge()
    stop_alice_leds()
    mode = (mode or "idle").lower()
    RUN.mkdir(parents=True, exist_ok=True)

    if mode in ("off",):
        subprocess.run(
            [sys.executable, str(ALICE_LEDS), "--sysfs", str(LED_SYSFS), "off"],
            check=False,
            timeout=5,
        )
        broadcast(
            {
                "state": "hw",
                "ui": "idle",
                "ring": ["#000000"] * 6,
                "clock": "--:--",
                "message": "leds off",
            }
        )
        return {"ok": True, "mode": "off"}

    if mode in ("idle", "clock"):
        args = [sys.executable, str(ALICE_LEDS), "--sysfs", str(LED_SYSFS), "clock"]
    elif mode in ("listen", "demo"):
        args = [sys.executable, str(ALICE_LEDS), "--sysfs", str(LED_SYSFS), "demo"]
    elif mode in ("speak",):
        led = PATTERNS / "alice_speaking.led"
        if not led.is_file():
            led = PATTERNS / "alice_listening.led"
        args = [sys.executable, str(ALICE_LEDS), "--sysfs", str(LED_SYSFS), "play", str(led)]
    elif mode in ("1234",):
        subprocess.run(
            [sys.executable, str(ALICE_LEDS), "--sysfs", str(LED_SYSFS), "1234"],
            check=False,
            timeout=5,
        )
        return {"ok": True, "mode": "1234"}
    else:
        return {"ok": False, "error": f"unknown alice mode: {mode}"}

    logf = open(RUN / "alice_leds.log", "ab", buffering=0)
    _alice_proc = subprocess.Popen(
        args,
        cwd=str(STAND),
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (RUN / "alice_leds.pid").write_text(str(_alice_proc.pid))
    return {"ok": True, "mode": mode, "pid": _alice_proc.pid}


def stop_qemu() -> dict[str, Any]:
    st = qemu_status()
    _kill_pid(st.get("tail_pid"))
    _kill_pid(st.get("qemu_pid"))
    _kill_pid(st.get("start_pid"))
    time.sleep(0.4)
    if qemu_status()["up"]:
        _pkill_patterns()
        time.sleep(0.5)
    for name in ("qemu.pid", "start.pid", "console_tail.pid"):
        try:
            (RUN / name).unlink(missing_ok=True)
        except Exception:
            pass
    broadcast({"state": "qemu", "up": False, "message": "QEMU stop"})
    return qemu_status()


def start_qemu() -> dict[str, Any]:
    if not START_SH.is_file():
        raise FileNotFoundError(f"нет {START_SH}")
    ensure_led_sysfs()
    ensure_led_bridge()
    RUN.mkdir(parents=True, exist_ok=True)
    # truncate console for clean boot view
    try:
        (RUN / "console.log").write_text("")
    except Exception:
        pass
    log = open(RUN / "start.log", "ab", buffering=0)
    proc = subprocess.Popen(
        ["/bin/bash", str(START_SH)],
        cwd=str(STAND),
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    time.sleep(0.6)
    # LED рисует гостевой led_util (qemu-arm), не хостовый alice_leds
    st = qemu_status()
    broadcast(
        {
            "state": "qemu",
            "up": True,
            "message": f"QEMU boot (launcher {proc.pid})",
        }
    )
    return {**st, "launcher_pid": proc.pid}


def clear_console() -> dict[str, Any]:
    try:
        (RUN / "console.log").write_text("")
    except Exception:
        pass
    broadcast({"state": "boot", "chunk": "— console cleared —"})
    return {"ok": True}


def run_action(action: str) -> dict[str, Any]:
    global _busy
    action = (action or "").strip().lower()
    if action in ("status",):
        return {"ok": True, **qemu_status()}

    with _ctl_lock:
        if _busy and action not in ("status",):
            return {"ok": False, "error": "busy", **qemu_status()}
        _busy = True
    try:
        if action in ("stop", "poweroff", "halt", "down"):
            st = stop_qemu()
            return {"ok": True, "action": "stop", **st}
        if action in ("boot", "start", "up", "power"):
            if qemu_status()["up"]:
                return {"ok": True, "action": "boot", "already": True, **qemu_status()}
            st = start_qemu()
            return {"ok": True, "action": "boot", **st}
        if action in ("reboot", "restart", "reset"):
            stop_qemu()
            time.sleep(0.5)
            st = start_qemu()
            return {"ok": True, "action": "reboot", **st}
        if action in ("clear", "cls", "clearlog"):
            clear_console()
            return {"ok": True, "action": "clear", **qemu_status()}
        return {"ok": False, "error": f"unknown action: {action}", **qemu_status()}
    finally:
        with _ctl_lock:
            _busy = False


class Handler(BaseHTTPRequestHandler):
    server_version = "mini2-viewer/1.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        # не спамим каждым led event
        if args and "/api/event" in str(args[0]):
            return
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            pass

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(ROOT / "index.html")
        if path == "/api/stream":
            return self._sse()
        if path == "/api/history":
            with _lock:
                events = list(_history)
            return self._json({"events": events})
        if path == "/api/health":
            return self._json({"ok": True, "clients": len(_clients)})
        if path == "/api/firmware":
            status = {"source": "backup" if (STAND / "mini2-backup.ext4").exists() else "demo", "fresh": False}
            try:
                report = json.loads((LED_SYSFS / ".firmware-status.json").read_text())
                status.update(report)
                status["fresh"] = 0 <= time.time() - report["timestamp"] < 20 and qemu_status()["up"]
            except (OSError, ValueError, KeyError, TypeError):
                pass
            return self._json(status)
        if path == "/api/qemu":
            return self._json({"ok": True, **qemu_status()})
        if path == "/api/console":
            log = RUN / "console.log"
            text = ""
            try:
                raw = log.read_bytes()
                # last ~48KB, strip CR
                raw = raw[-48_000:]
                text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                lines = text.split("\n")
                if len(lines) > 400:
                    text = "\n".join(lines[-400:])
            except Exception:
                text = ""
            return self._json({"ok": True, "text": text, "size": log.stat().st_size if log.is_file() else 0})
        rel = path.lstrip("/")
        if ".." in rel:
            self.send_error(400)
            return
        fp = (ROOT / rel).resolve()
        if not str(fp).startswith(str(ROOT)) or not fp.is_file():
            self.send_error(404)
            return
        self._file(fp)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 1_000_000:
            self.send_error(413)
            return
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(body, dict):
                raise ValueError("object expected")
        except Exception as e:
            return self._json({"error": str(e)}, code=400)

        if path == "/api/event":
            broadcast(body)
            return self._json({"ok": True})

        if path == "/api/qemu":
            action = body.get("action") or body.get("cmd") or ""
            try:
                result = run_action(str(action))
                code = 200 if result.get("ok") else 400
                return self._json(result, code=code)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, code=500)

        if path == "/api/alice":
            mode = body.get("mode") or body.get("action") or "idle"
            try:
                result = start_alice_leds(str(mode))
                code = 200 if result.get("ok") else 400
                return self._json(result, code=code)
            except Exception as e:
                return self._json({"ok": False, "error": str(e)}, code=500)

        self.send_error(404)

    def _file(self, fp: Path) -> None:
        data = fp.read_bytes()
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", MIME.get(fp.suffix.lower(), "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj: Any, code: int = 200) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self) -> None:
        cid = uuid.uuid4().hex
        q: queue.Queue = queue.Queue(maxsize=64)
        with _lock:
            _clients[cid] = q
            snap = list(_history[-20:])
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            for ev in snap:
                self._sse_write(ev)
            while True:
                try:
                    ev = q.get(timeout=15)
                    self._sse_write(ev)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with _lock:
                _clients.pop(cid, None)

    def _sse_write(self, ev: dict[str, Any]) -> None:
        payload = json.dumps(ev, ensure_ascii=False)
        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
        self.wfile.flush()


def main() -> None:
    ensure_led_sysfs()
    # bridge/alice стартует run_stand.sh — сервер только HTTP
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"Mini 2 viewer → http://{HOST}:{PORT}/", flush=True)
    print("POST /api/qemu {action: boot|stop|reboot|clear}", flush=True)
    print("POST /api/alice {mode: idle|listen|speak|off}", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nstop", flush=True)


if __name__ == "__main__":
    main()
