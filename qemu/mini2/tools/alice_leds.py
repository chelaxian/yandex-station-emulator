#!/usr/bin/env python3
"""Virtual Alice LED subsystem: writes Mini2 sysfs like maind/led_util.

  Modes:
    clock          — idle HH:MM on matrix (guest/host time)
    play <file.led>— play oknix .led pattern to ring
    demo           — listen pattern loop + clock
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYSFS = ROOT / "led_sysfs"
PATTERNS = ROOT / "rootfs_files" / "system" / "vendor" / "quasar" / "ledpatterns" / "oknix"

DIGIT = {
    "0": "ABCDEF",
    "1": "BC",
    "2": "ABDEG",
    "3": "ABCDG",
    "4": "BCFG",
    "5": "ACDFG",
    "6": "ACDEFG",
    "7": "ABC",
    "8": "ABCDEFG",
    "9": "ABCDFG",
    " ": "",
    "-": "G",
}


def w(path: Path, val: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{max(0, min(255, int(val)))}\n")


def set_ring(sysfs: Path, colors: list[str], scale: float = 1.0) -> None:
    for i, hex6 in enumerate(colors[:6], start=1):
        hex6 = hex6.strip().lstrip("#")
        if len(hex6) != 6:
            continue
        r, g, b = int(hex6[0:2], 16), int(hex6[2:4], 16), int(hex6[4:6], 16)
        r, g, b = int(r * scale), int(g * scale), int(b * scale)
        w(sysfs / f"mini2:red:ring{i}" / "brightness", r)
        w(sysfs / f"mini2:green:ring{i}" / "brightness", g)
        w(sysfs / f"mini2:blue:ring{i}" / "brightness", b)


def clear_ring(sysfs: Path) -> None:
    set_ring(sysfs, ["000000"] * 6)


def clear_clock(sysfs: Path) -> None:
    for p in sysfs.glob("mini2:white:clock*/brightness"):
        w(p, 0)


def set_digit(sysfs: Path, pos: int, ch: str, bri: int = 180) -> None:
    segs = DIGIT.get(ch, "ABCDEFG")
    for s in "ABCDEFG":
        w(sysfs / f"mini2:white:clock{s}{pos}" / "brightness", bri if s in segs else 0)


def set_clock(sysfs: Path, text: str, degree: bool = False, bri: int = 180) -> None:
    clear_clock(sysfs)
    # normalize to d1 d2 : d3 d4
    t = text.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", t):
        hh, mm = t.split(":")
        d1, d2 = f"{int(hh):02d}"
        d3, d4 = mm
        colon = True
    elif re.fullmatch(r"\d{4}", t):
        d1, d2, d3, d4 = t
        colon = True
    else:
        padded = (t + "    ")[:5]
        d1, d2, mid, d3, d4 = padded[0], padded[1], padded[2], padded[3], padded[4]
        colon = mid == ":"
        set_digit(sysfs, 1, d1, bri)
        set_digit(sysfs, 2, d2, bri)
        set_digit(sysfs, 3, d3, bri)
        set_digit(sysfs, 4, d4, bri)
        if colon:
            w(sysfs / "mini2:white:clockPLUS1" / "brightness", bri)
            w(sysfs / "mini2:white:clockPLUS2" / "brightness", bri)
        if degree:
            w(sysfs / "mini2:white:clockDEGREE" / "brightness", bri)
        return

    set_digit(sysfs, 1, d1, bri)
    set_digit(sysfs, 2, d2, bri)
    set_digit(sysfs, 3, d3, bri)
    set_digit(sysfs, 4, d4, bri)
    if colon:
        w(sysfs / "mini2:white:clockPLUS1" / "brightness", bri)
        w(sysfs / "mini2:white:clockPLUS2" / "brightness", bri)
    if degree:
        w(sysfs / "mini2:white:clockDEGREE" / "brightness", bri)


def parse_led_frames(text: str) -> list[tuple[list[str], int]]:
    frames = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low in ("loop",) or low.startswith("gammacorrection") or low.startswith("smooth"):
            continue
        if low.startswith("rotate") or low.startswith("gradient"):
            # simplified: skip complex directives for now
            continue
        parts = line.split()
        if len(parts) < 7:
            continue
        colors, dur = parts[:6], int(parts[6])
        if all(re.fullmatch(r"[0-9a-fA-F]{6}", c) for c in colors):
            frames.append((colors, max(1, dur)))
    return frames


def play_led(sysfs: Path, path: Path, loops: int = 0) -> None:
    frames = parse_led_frames(path.read_text())
    if not frames:
        print(f"no frames in {path}", file=sys.stderr)
        return
    n = 0
    while True:
        for colors, dur in frames:
            set_ring(sysfs, colors)
            time.sleep(dur / 1000.0)
        n += 1
        if loops and n >= loops:
            break


def mode_clock(sysfs: Path) -> None:
    clear_ring(sysfs)
    while True:
        set_clock(sysfs, datetime.now().strftime("%H:%M"))
        time.sleep(1)


def mode_demo(sysfs: Path) -> None:
    listen = PATTERNS / "alice_listening.led"
    frames = parse_led_frames(listen.read_text()) if listen.is_file() else []
    fi = 0
    while True:
        set_clock(sysfs, datetime.now().strftime("%H:%M"))
        if frames:
            colors, dur = frames[fi % len(frames)]
            set_ring(sysfs, colors)
            fi += 1
            time.sleep(dur / 1000.0)
        else:
            set_ring(sysfs, ["4aa3ff"] * 6)
            time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sysfs", default=str(DEFAULT_SYSFS))
    ap.add_argument("mode", choices=["clock", "demo", "play", "off", "1234"])
    ap.add_argument("led", nargs="?", help=".led file for play")
    args = ap.parse_args()
    sysfs = Path(args.sysfs)
    if not sysfs.is_dir():
        print("run mk_led_sysfs.py first", file=sys.stderr)
        return 1

    if args.mode == "off":
        clear_ring(sysfs)
        clear_clock(sysfs)
        return 0
    if args.mode == "1234":
        set_clock(sysfs, "12:34")
        set_ring(sysfs, ["6b0fff"] * 6)
        return 0
    if args.mode == "clock":
        mode_clock(sysfs)
    if args.mode == "demo":
        mode_demo(sysfs)
    if args.mode == "play":
        path = Path(args.led or PATTERNS / "alice_listening.led")
        play_led(sysfs, path, loops=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
