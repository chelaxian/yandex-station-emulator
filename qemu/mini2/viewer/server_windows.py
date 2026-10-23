#!/usr/bin/env python3
"""Mini 2 viewer — UI + SSE + QEMU control (Windows port of server.py).

  python server_windows.py   # http://127.0.0.1:8765/

Differences from server.py:
- boots QEMU via tools/start_windows.py (no bash, no 9p);
- LED data comes from viewer/led_bridge_windows.py (TCP) — the host-side
  fake sysfs tree is not required on Windows;
- firmware status is read from run/.firmware-status.json written by the
  LED bridge; process management uses cross-platform os.kill.
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
START_WIN = STAND / "tools" / "start_windows.py"
RUN = STAND / "run"
LED_SYSFS = STAND / "led_sysfs"
LED_BRIDGE = ROOT / "led_bridge_windows.py"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))

IS_WIN = os.name == "nt"
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
    """Cross-platform liveness check.

    os.kill(pid, 0) is POSIX-only: on Windows CPython maps it to
    GenerateConsoleCtrlEvent/TerminateProcess instead of a probe, so a
    status poll could signal or kill the process. Use the Win32 API there.
    """
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def qemu_status() -> dict[str, Any]:
    qemu_pid = _read_pid("qemu.pid")
    start_pid = _read_pid("start.pid")
    tail_pid = _read_pid("console_tail.pid")
    up = _alive(qemu_pid)
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
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=5)
        else:
            os.kill(pid, sig)
    except (OSError, subprocess.SubprocessError):
        pass


def ensure_led_bridge() -> None:
    global _bridge_proc
    if _bridge_proc and _bridge_proc.poll() is None:
        return
    if _alive(_read_pid("led_bridge.pid")):
        return
    RUN.mkdir(parents=True, exist_ok=True)
    log = open(RUN / "led_bridge.log", "ab", buffering=0)
    kwargs: dict = {"stdout": log, "stderr": subprocess.STDOUT}
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    _bridge_proc = subprocess.Popen([sys.executable, str(LED_BRIDGE)], cwd=str(STAND), **kwargs)
    (RUN / "led_bridge.pid").write_text(str(_bridge_proc.pid))


def stop_qemu() -> dict[str, Any]:
    st = qemu_status()
    _kill_pid(st.get("tail_pid"))
    _kill_pid(st.get("qemu_pid"))
    _kill_pid(st.get("start_pid"))
    time.sleep(0.4)
    for name in ("qemu.pid", "start.pid", "console_tail.pid"):
        try:
            (RUN / name).unlink(missing_ok=True)
        except Exception:
            pass
    broadcast({"state": "qemu", "up": False, "message": "QEMU stop"})
    return qemu_status()


def start_qemu() -> dict[str, Any]:
    if not START_WIN.is_file():
        raise FileNotFoundError(f"нет {START_WIN}")
    ensure_led_bridge()
    RUN.mkdir(parents=True, exist_ok=True)
    try:
        (RUN / "console.log").write_text("")
    except Exception:
        pass
    log = open(RUN / "start.log", "ab", buffering=0)
    kwargs: dict = {"stdout": log, "stderr": subprocess.STDOUT}
    if IS_WIN:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen([sys.executable, str(START_WIN)], cwd=str(STAND), **kwargs)
    time.sleep(0.6)
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


def firmware_status() -> dict[str, Any]:
    status = {"source": "backup" if (STAND / "mini2-backup.ext4").exists() else "demo", "fresh": False}
    for candidate in (RUN / ".firmware-status.json", LED_SYSFS / ".firmware-status.json"):
        try:
            report = json.loads(candidate.read_text())
            status.update(report)
            # freshness by the HOST-side file mtime (the LED bridge rewrites
            # the file every ~5 s). The guest timestamp can be skewed when the
            # guest/host clocks drift apart, which falsely showed "no data".
            try:
                age = time.time() - candidate.stat().st_mtime
            except OSError:
                age = None
            status["fresh"] = (
                age is not None and 0 <= age < 20 and qemu_status()["up"]
            )
            break
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return status


class Handler(BaseHTTPRequestHandler):
    server_version = "mini2-viewer-win/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
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
            return self._json(firmware_status())
        if path == "/api/qemu":
            return self._json({"ok": True, **qemu_status()})
        if path == "/api/console":
            log = RUN / "console.log"
            text = ""
            try:
                raw = log.read_bytes()
                raw = raw[-48_000:]
                text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
                lines = text.split("\n")
                if len(lines) > 400:
                    text = "\n".join(lines[-400:])
            except Exception:
                text = ""
            return self._json({"ok": True, "text": text, "size": log.stat().st_size if log.is_file() else 0})
        if path == "/api/hardware":
            try:
                return self._json(json.loads((RUN / "hardware.json").read_text()))
            except Exception:
                return self._json({})
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
    ensure_led_bridge()
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    httpd.daemon_threads = True
    print(f"Mini 2 viewer -> http://{HOST}:{PORT}/", flush=True)
    try:
        httpd.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nstop", flush=True)


# Detached launches redirect stdout to files: force UTF-8 so prints
# with non-ASCII never crash on cp1251/cp866 consoles (Python 3.10).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    main()
