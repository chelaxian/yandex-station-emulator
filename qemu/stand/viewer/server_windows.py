#!/usr/bin/env python3
"""Stand panel: pick Mini 2 or MIDI, boot/stop/reboot, watch the console."""
from __future__ import annotations

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from stand import config, led, qemu

ROOT = Path(__file__).resolve().parent
PORT = 8765
LOCK = threading.Lock()
STATE: dict = {"stand": None}
LED = led.Bridge()


def current() -> qemu.Stand | None:
    return STATE["stand"]


def ensure(model_name: str) -> qemu.Stand:
    stand = current()
    if stand and stand.model["id"] == model_name:
        return stand
    if stand:
        stand.stop()
    LED.reset()
    stand = qemu.Stand(model_name)
    STATE["stand"] = stand
    return stand


def state() -> dict:
    stand = current()
    models = []
    for name, m in config.MODELS.items():
        models.append({
            "id": name,
            "title": m["title"],
            "short": m["short"],
            "cpu": m["cpu"],
            "missing": [str(p) for p in config.missing(m)],
        })
    return {
        "model": stand.model["id"] if stand else None,
        "up": bool(stand and stand.alive()),
        "pid": stand.pid() if stand else None,
        "console": str(stand.console_log) if stand else None,
        "models": models,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "stand-panel/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path):
        data = path.read_bytes()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
        }.get(path.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._file(ROOT / "index.html")
        if path == "/style.css":
            # shared with the original Mini 2 panel, not copied
            return self._file(ROOT.parents[1] / "mini2" / "viewer" / "style.css")
        if path in ("/style-extra.css", "/app.js"):
            return self._file(ROOT / path.lstrip("/"))
        if path == "/api/state":
            with LOCK:
                return self._json(state())
        if path == "/api/led":
            return self._json(LED.snapshot())
        if path == "/api/console":
            stand = current()
            text = ""
            if stand:
                try:
                    raw = stand.console_log.read_bytes()[-60000:]
                    text = raw.decode("utf-8", "replace").replace("\r", "")
                except OSError:
                    pass
            return self._json({"ok": True, "text": text})
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        with LOCK:
            if path == "/api/select":
                model = body.get("model") or "mini"
                try:
                    ensure(model)
                except SystemExit as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
                return self._json({"ok": True, **state()})
            if path == "/api/boot":
                model = body.get("model") or "mini"
                try:
                    model_def = config.model(model)
                except SystemExit as e:
                    return self._json({"ok": False, "error": str(e)}, 400)
                missing = [str(p) for p in config.missing(model_def)]
                if missing:
                    return self._json({
                        "ok": False,
                        "error": f"нет файлов модели «{model_def['short']}»",
                        "missing": missing,
                        "hint": config.install_command(model),
                    }, 400)
                try:
                    stand = ensure(model)
                except SystemExit as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
                try:
                    if not stand.alive():
                        stand.start()
                        LED.reset()
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
                return self._json({"ok": True, **state()})
            if path == "/api/qemu":
                stand = current()
                action = (body.get("action") or "").lower()
                if not stand:
                    return self._json({"ok": False, "error": "no model selected"}, 400)
                try:
                    if action == "stop":
                        stand.stop()
                        LED.reset()
                        if stand.alive():
                            return self._json({"ok": False, "error": "QEMU не завершился"}, 500)
                    elif action == "reboot":
                        stand.reboot()
                        LED.reset()
                    elif action == "clear":
                        try:
                            stand.console_log.write_text("")
                        except OSError:
                            pass
                    elif action == "boot":
                        if not stand.alive():
                            stand.start()
                            LED.reset()
                    else:
                        return self._json({"ok": False, "error": f"unknown action {action}"}, 400)
                except RuntimeError as e:
                    return self._json({"ok": False, "error": str(e)}, 500)
                return self._json({"ok": True, **state()})
        self.send_error(404)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=PORT)
    a = ap.parse_args()
    LED.start()
    httpd = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    httpd.daemon_threads = True
    print(f"Stand panel -> http://127.0.0.1:{a.port}/", flush=True)
    try:
        httpd.serve_forever(0.5)
    except KeyboardInterrupt:
        stand = current()
        if stand:
            stand.stop()


if __name__ == "__main__":
    main()
