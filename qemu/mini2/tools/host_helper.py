#!/usr/bin/env python3
"""Windows replacement for HardwareBridge.app (host side).

Roles (loopback-only):
- TCP 19093: microphone PCM server — the guest mic_relay connects and pulls
  raw stereo S16_LE @ 48 kHz. On Windows the capture uses sounddevice
  (WASAPI); if PortAudio is unavailable the listener still accepts
  connections and reports the error in run/hardware.json.
- HTTP 19094: /epoch and /keys/{private,public}.pem — the guest bootstrap
  fetches the clock and the PEM pair from here instead of a 9p share.
- run/hardware.json: live status for the viewer panel (same schema as the
  macOS HardwareBridge).
"""
from __future__ import annotations

import json
import math
import os
import queue
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
RUN = STAND / "run"
REPO = STAND.parents[1]  # repo root (qemu/mini2 -> repo)
PEM_SOURCE = Path(os.environ.get("PEM_SOURCE_DIR") or (REPO / "keys"))
MIC_PORT = 19093
HTTP_PORT = 19094

_state: dict = {"bluetooth": "not supported on this host", "microphone": "starting"}
_state_lock = threading.Lock()


def save() -> None:
    _state["timestamp"] = time.time()
    RUN.mkdir(parents=True, exist_ok=True)
    try:
        (RUN / "hardware.json").write_text(json.dumps(_state, sort_keys=True))
    except OSError:
        pass


# ---------------------------------------------------------------- microphone


class MicSource:
    """Capture thread -> PCM chunks + RMS, independent of client connections."""

    def __init__(self) -> None:
        self.pcm: queue.Queue = queue.Queue(maxsize=32)
        self.ok = False
        self.error = ""
        self.channels = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except Exception as e:
            with _state_lock:
                _state["microphone"] = f"capture unavailable: sounddevice not installed ({e})"
                save()
            return

        def make_callback(channels: int):
            def callback(in_data, frame_count, time_info, status):
                data = bytes(in_data)
                if channels == 1:
                    # mono device -> duplicate samples into stereo frames
                    mono = data
                    data = b"".join(mono[i : i + 2] * 2 for i in range(0, len(mono), 2))
                # stereo interleaved S16LE -> RMS over all samples
                count = len(data) // 2
                if count:
                    acc = 0
                    for i in range(0, count, 16):  # sparse sampling is enough for RMS
                        v = int.from_bytes(data[i * 2 : i * 2 + 2], "little", signed=True)
                        acc += v * v
                    rms = math.sqrt(acc / max(1, count // 16)) / 32768
                    with _state_lock:
                        _state["mic_rms"] = round(rms, 5)
                        _state["microphone"] = "capturing"
                        save()
                try:
                    self.pcm.put_nowait(data)
                except queue.Full:
                    pass  # drop — keep latency bounded
                return None, 0
            return callback

        # Prefer stereo S16LE @48k; fall back to a mono input device.
        try:
            stream = sd.RawInputStream(
                samplerate=48000, channels=2, dtype="int16",
                callback=make_callback(2), blocksize=1024,
            )
            self.channels = 2
        except Exception:
            stream = sd.RawInputStream(
                samplerate=48000, channels=1, dtype="int16",
                callback=make_callback(1), blocksize=1024,
            )
            self.channels = 1
        try:
            stream.start()
            self.ok = True
            with _state_lock:
                _state["microphone"] = "capturing"
                save()
            while True:
                time.sleep(3600)
        except Exception as e:
            with _state_lock:
                _state["microphone"] = f"capture unavailable: {e}"
                save()


# ------------------------------------------------------------ ble staging

def ble_stage_dir() -> Path:
    """Directory for one-shot GATT write payloads (served to the guest).

    hardware_rpc stages base64 payloads here instead of writing into
    alpine_root — with the embedded Windows initramfs, host writes to
    alpine_root never reach the guest. The guest fetches them via
    http://10.0.2.2:19094/ble-rpc/<name>, keeping credentials out of the
    serial console echo.
    """
    d = RUN / "ble-rpc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def mic_server() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", MIC_PORT))
    srv.listen(8)
    print(f"mic PCM server -> 127.0.0.1:{MIC_PORT}", flush=True)

    source = MicSource()
    source.thread.start()

    def client_loop(conn: socket.socket) -> None:
        with _state_lock:
            _state["mic_clients"] = _state.get("mic_clients", 0) + 1
            save()
        try:
            while True:
                if source.ok:
                    try:
                        chunk = source.pcm.get(timeout=1)
                    except queue.Empty:
                        continue
                    conn.sendall(chunk)
                else:
                    # keep the socket warm while capture is down
                    time.sleep(0.5)
                    conn.settimeout(0.1)
                    try:
                        if conn.recv(1):
                            pass
                    except socket.timeout:
                        continue
                    except OSError:
                        return
        except OSError:
            pass
        finally:
            with _state_lock:
                _state["mic_clients"] = max(0, _state.get("mic_clients", 1) - 1)
                save()

    while True:
        try:
            conn, _ = srv.accept()
        except OSError:
            time.sleep(0.5)
            continue
        threading.Thread(target=client_loop, args=(conn,), daemon=True).start()


# -------------------------------------------------------------------- http


class Helper(ThreadingHTTPServer):
    daemon_threads = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # never log PEM contents
        pass

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/epoch":
            body = str(int(time.time())).encode()
        elif path in ("/keys/private.pem", "/keys/public.pem"):
            fp = PEM_SOURCE / Path(path).name
            try:
                body = fp.read_bytes()
            except OSError:
                self.send_error(404)
                return
        elif path == "/health":
            with _state_lock:
                body = json.dumps(_state).encode()
        elif path.startswith("/ble-rpc/"):
            fp = ble_stage_dir() / Path(path).name
            try:
                body = fp.read_bytes()
            except OSError:
                self.send_error(404)
                return
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    RUN.mkdir(parents=True, exist_ok=True)
    save()
    threading.Thread(target=mic_server, daemon=True).start()
    print(f"helper HTTP -> http://127.0.0.1:{HTTP_PORT}/epoch", flush=True)
    Helper(("127.0.0.1", HTTP_PORT), Handler).serve_forever()
    return 0


# Detached launches redirect stdout to files: force UTF-8 so prints
# with non-ASCII never crash on cp1251/cp866 consoles (Python 3.10).
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

if __name__ == "__main__":
    sys.exit(main())
