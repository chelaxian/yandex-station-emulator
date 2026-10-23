#!/usr/bin/env python3
"""Create fake Mini 2 LED class sysfs (ring RGB×6 + white clock segments)."""
from __future__ import annotations

import argparse
from pathlib import Path

RING = range(1, 7)
CLOCK_DIGITS = [f"{s}{d}" for d in range(1, 5) for s in "ABCDEFG"]
CLOCK_EXTRA = ["PLUS1", "PLUS2", "PLUS3", "PLUS4", "MINUS", "DEGREE"]


def make_led(root: Path, name: str) -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "brightness").write_text("0\n")
    (d / "max_brightness").write_text("255\n")
    # Mini2 init writes brightness_scale; keep as stub
    (d / "brightness_scale").write_text("0\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "led_sysfs"),
    )
    args = ap.parse_args()
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)

    for i in RING:
        for color in ("red", "green", "blue"):
            make_led(root, f"mini2:{color}:ring{i}")
    for loc in CLOCK_DIGITS + CLOCK_EXTRA:
        make_led(root, f"mini2:white:clock{loc}")

    print(f"LED sysfs → {root} ({sum(1 for _ in root.iterdir())} leds)")


if __name__ == "__main__":
    main()
