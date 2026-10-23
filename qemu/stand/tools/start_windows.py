#!/usr/bin/env python3
"""Two-model entry point: ``python start_windows.py --model mini|midi``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stand import config, qemu


def check(model_name: str, qemu_path: str | None = None) -> int:
    """Preflight: report missing images/initramfs and the install command."""
    m = config.model(model_name)
    problems = [f"нет файла: {path}" for path in config.missing(m)]
    if not qemu_path:
        try:
            qemu.find_qemu()
        except SystemExit as e:
            problems.append(str(e))
    if problems:
        print(f"Проверка «{m['title']}»:")
        for problem in problems:
            print(f"  {problem}")
        print(f"  установите данные: {config.install_command(model_name)}")
        return 2
    print(f"«{m['title']}»: данные на месте.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Yandex Station emulator stand")
    ap.add_argument("--model", choices=sorted(config.MODELS), default="mini")
    ap.add_argument("--audio", help="dsound | wasapi | sdl | none (default: model config)")
    ap.add_argument("--console-port", type=int, default=19096)
    ap.add_argument("--detach", action="store_true", help="start in background and return")
    ap.add_argument("--qemu", help="path to qemu-system-aarch64")
    ap.add_argument("--check", action="store_true", help="only verify that model data is installed")
    a = ap.parse_args()

    if a.check:
        return check(a.model, a.qemu)

    model = config.model(a.model)
    missing = config.missing(model)
    if missing:
        print("Нет файлов модели:", file=sys.stderr)
        for path in missing:
            print(f"  {path}", file=sys.stderr)
        print(f"Установите данные: {config.install_command(a.model)}", file=sys.stderr)
        return 2

    stand = qemu.Stand(a.model, audio=a.audio, console_port=a.console_port, qemu=a.qemu)
    if a.detach:
        try:
            proc = stand.start()
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 2
        print(f"{model['title']}: QEMU pid {proc.pid}, console 127.0.0.1:{a.console_port}")
        for rule in model.get("hostfwd") or ():
            print(f"  проброс: {rule}")
        return 0

    print(f"{model['title']}: console 127.0.0.1:{a.console_port}, audio={stand.audio}")
    try:
        return qemu.wait(stand)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
