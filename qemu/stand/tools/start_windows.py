#!/usr/bin/env python3
"""Two-model entry point: ``python start_windows.py --model mini|midi``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stand import config, qemu


def main() -> int:
    ap = argparse.ArgumentParser(description="Yandex Station emulator stand")
    ap.add_argument("--model", choices=sorted(config.MODELS), default="mini")
    ap.add_argument("--audio", help="dsound | wasapi | sdl | none (default: model config)")
    ap.add_argument("--console-port", type=int, default=19096)
    ap.add_argument("--detach", action="store_true", help="start in background and return")
    ap.add_argument("--qemu", help="path to qemu-system-aarch64")
    a = ap.parse_args()

    model = config.model(a.model)
    missing = config.missing(model)
    if missing:
        print("Нет файлов модели:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        return 2

    stand = qemu.Stand(a.model, audio=a.audio, console_port=a.console_port, qemu=a.qemu)
    if a.detach:
        proc = stand.start()
        print(f"{model['title']}: QEMU pid {proc.pid}, console 127.0.0.1:{a.console_port}")
        return 0

    print(f"{model['title']}: console 127.0.0.1:{a.console_port}, audio={stand.audio}")
    return qemu.wait(stand)


if __name__ == "__main__":
    sys.exit(main())
