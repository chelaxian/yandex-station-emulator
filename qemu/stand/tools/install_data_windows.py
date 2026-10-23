#!/usr/bin/env python3
"""Install Windows stand data: Mini 2 runtime + MIDI disk images.

Mini 2 runtime comes from the repository assets (install_runtime_windows.py).
MIDI images are stored in this folder as a split gzip archive; they are
verified against midi-manifest.json, joined and unpacked into data/midi/.
Run once before the first launch.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
REPO = STAND.parents[1]
ASSETS = STAND / "assets"
DATA = STAND / "data"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def join_parts(manifest: dict, out: Path) -> None:
    spec = manifest["rootfs"]
    with out.open("wb") as dst:
        for part in spec["parts"]:
            path = ASSETS / part["file"]
            if not path.is_file() or path.stat().st_size != part["size"] or sha256(path) != part["sha256"]:
                raise SystemExit(f"Checksum mismatch: {path.name}")
            with path.open("rb") as src:
                shutil.copyfileobj(src, dst)
    if out.stat().st_size != spec["size"] or sha256(out) != spec["sha256"]:
        raise SystemExit("Checksum mismatch: joined MIDI rootfs archive")


def gunzip(src: Path, dst: Path) -> None:
    with gzip.open(src, "rb") as fin, dst.open("wb") as fout:
        shutil.copyfileobj(fin, fout)


def install_midi() -> None:
    manifest = json.loads((ASSETS / "midi-manifest.json").read_text())
    target = DATA / "midi"
    rootfs = target / "rootfs.ext4"
    data = target / "data.ext4"
    target.mkdir(parents=True, exist_ok=True)
    if not rootfs.is_file():
        print("MIDI: joining rootfs parts…")
        archive = target / "rootfs.ext4.gz"
        join_parts(manifest, archive)
        print("MIDI: unpacking rootfs.ext4…")
        gunzip(archive, rootfs)
        archive.unlink()
    if not data.is_file():
        spec = manifest["data"]
        src = ASSETS / spec["file"]
        if not src.is_file() or src.stat().st_size != spec["size"] or sha256(src) != spec["sha256"]:
            raise SystemExit(f"Checksum mismatch: {src.name}")
        print("MIDI: unpacking data.ext4…")
        gunzip(src, data)
    initrd = target / "initramfs-midi.cpio.gz"
    if not initrd.is_file():
        alpine_root = REPO / "qemu" / "mini2" / "alpine_root"
        if not (alpine_root / "bin").is_dir():
            raise SystemExit("Mini 2 runtime is missing — run with --model mini first")
        sys.path.insert(0, str(STAND / "tools"))
        from stand import build as stand_build

        print("MIDI: building initramfs…")
        stand_build.build("midi", alpine_root, initrd)
    print("MIDI images installed:", target)


def install_mini() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    mini = REPO / "qemu" / "mini2"
    if not (mini / "mini2-backup.ext4").is_file():
        print("Mini 2: unpacking runtime…")
        subprocess.run([sys.executable, str(REPO / "scripts" / "install_runtime_windows.py")], check=True, env=env)
    else:
        print("Mini 2: runtime present.")
    if not (mini / "alpine" / "initramfs-win.cpio.gz").is_file():
        print("Mini 2: building Windows initramfs…")
        sys.path.insert(0, str(STAND / "tools"))
        from stand import build as stand_build

        stand_build.build("mini", mini / "alpine_root", mini / "alpine" / "initramfs-win.cpio.gz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=("all", "mini", "midi"), default="all")
    a = ap.parse_args()
    if a.model in ("all", "mini"):
        install_mini()
    if a.model in ("all", "midi"):
        install_midi()
    print("Done. Launch: powershell -ExecutionPolicy Bypass -File qemu\\stand\\run_stand_windows.ps1 -Model midi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
