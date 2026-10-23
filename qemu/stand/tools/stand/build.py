"""Build a self-contained initramfs for one model from the Alpine bootstrap."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import cpio, config

ROOT = config.ROOT
GUEST = ROOT / "guest"
META = config.MINI2 / "run" / "win-runtime-meta.json"

INITTAB = (
    "::sysinit:/etc/local.d/{start}\n"
    "ttyAMA0::respawn:-/bin/sh\n"
    "::shutdown:/bin/busybox umount -a -r\n"
)


def load_meta(alpine_root: Path) -> dict[str, dict]:
    """POSIX metadata manifest from install_runtime_windows (Windows has no exec bits)."""
    if alpine_root.resolve() != (config.MINI2 / "alpine_root").resolve() or not META.is_file():
        return {}
    try:
        data = json.loads(META.read_text())
    except ValueError:
        return {}
    prefix = "qemu/mini2/alpine_root/"
    return {k[len(prefix):]: v for k, v in data.items() if k.startswith(prefix)}


def read_guest(name: str) -> bytes:
    """Guest scripts must be LF-only: git autocrlf turns them into CRLF."""
    return (GUEST / name).read_bytes().replace(b"\r\n", b"\n")


def build(model_name: str, alpine_root: Path, out: Path | None = None) -> Path:
    m = config.model(model_name)
    out = out or m["initrd"]
    start_script = "mini2.start" if model_name == "mini" else "midi.start"
    overlay = {
        "init": (read_guest("init-windows"), 0o755),
        f"etc/local.d/{start_script}": (read_guest(f"{m['guest']}-windows.start"), 0o755),
        "etc/inittab": (INITTAB.format(start=start_script).encode(), 0o644),
    }
    if model_name == "midi":
        # The Mini 2 bootstrap has no /opt/midi; MIDI's asound.conf lives there.
        overlay["opt/midi"] = (b"", 0o040755)
        overlay["opt/midi/asound.conf"] = (read_guest("asound.conf"), 0o644)
    files = cpio.build_initramfs(alpine_root, overlay, out, load_meta(alpine_root))
    print(f"{out}: {out.stat().st_size / 1e6:.1f} MB ({files} files)")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=sorted(config.MODELS), required=True)
    ap.add_argument("--alpine-root", type=Path, required=True)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    build(a.model, a.alpine_root, a.out)


if __name__ == "__main__":
    main()
