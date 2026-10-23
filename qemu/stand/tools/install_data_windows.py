#!/usr/bin/env python3
"""Install Windows stand data: Mini 2 runtime + MIDI disk images.

Mini 2 runtime comes from the repository assets (install_runtime_windows.py).
MIDI images are stored in this folder as a split gzip archive; they are
verified against midi-manifest.json, joined and unpacked into data/midi/.
Run once before the first launch.

Unpacking is atomic: images are written to a temporary file, checked for the
ext4 superblock magic, fsynced and only then renamed into place. A killed
installer therefore never leaves a half-written rootfs.ext4 behind.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
REPO = STAND.parents[1]
ASSETS = STAND / "assets"
DATA = STAND / "data"

SUPERBLOCK_OFFSET = 1024
EXT4_MAGIC = b"\x53\xef"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def matches(path: Path, size: int, digest: str) -> bool:
    return path.is_file() and path.stat().st_size == size and sha256(path) == digest


def ext4_expected_size(path: Path) -> int | None:
    """Image size implied by the ext4 superblock (None when it is not ext4)."""
    try:
        with path.open("rb") as f:
            f.seek(SUPERBLOCK_OFFSET)
            sb = f.read(1024)
    except OSError:
        return None
    if len(sb) < 0x154 or sb[0x38:0x3A] != EXT4_MAGIC:
        return None
    try:
        block_size = 1024 << struct.unpack_from("<I", sb, 0x18)[0]
        blocks = struct.unpack_from("<I", sb, 0x4)[0]
        if struct.unpack_from("<I", sb, 0x60)[0] & 0x80:  # INCOMPAT_64BIT
            blocks |= struct.unpack_from("<I", sb, 0x150)[0] << 32
    except struct.error:
        return None
    if block_size < 1024 or block_size > 65536 or blocks == 0:
        return None
    return blocks * block_size


def is_ext4(path: Path) -> bool:
    """True for ext4 whose file is not shorter than its superblock describes.

    A bare magic check accepted images truncated right after the superblock;
    comparing the file length with s_blocks_count * block_size catches that.
    """
    expected = ext4_expected_size(path)
    if expected is None:
        return False
    try:
        return path.stat().st_size >= expected
    except OSError:
        return False


def tmp_path(path: Path) -> Path:
    return path.with_name(path.name + ".tmp")


def join_parts(manifest: dict, out: Path) -> None:
    spec = manifest["rootfs"]
    tmp = tmp_path(out)
    try:
        with tmp.open("wb") as dst:
            for part in spec["parts"]:
                path = ASSETS / part["file"]
                if not matches(path, part["size"], part["sha256"]):
                    raise SystemExit(f"Checksum mismatch: {path.name}")
                with path.open("rb") as src:
                    shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        if tmp.stat().st_size != spec["size"] or sha256(tmp) != spec["sha256"]:
            raise SystemExit("Checksum mismatch: joined MIDI rootfs archive")
        os.replace(tmp, out)
    finally:
        tmp.unlink(missing_ok=True)


def gunzip(src: Path, dst: Path) -> None:
    """Unpack a disk image atomically; validate ext4 before publishing it."""
    tmp = tmp_path(dst)
    try:
        with gzip.open(src, "rb") as fin, tmp.open("wb") as fout:
            shutil.copyfileobj(fin, fout)
            fout.flush()
            os.fsync(fout.fileno())
        if not is_ext4(tmp):
            raise SystemExit(f"Unpacked image is not ext4: {dst.name}")
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def install_midi() -> None:
    manifest = json.loads((ASSETS / "midi-manifest.json").read_text())
    target = DATA / "midi"
    rootfs = target / "rootfs.ext4"
    data = target / "data.ext4"
    target.mkdir(parents=True, exist_ok=True)

    if not is_ext4(rootfs):
        if rootfs.exists():
            print("MIDI: rootfs.ext4 повреждён или неполный — пересобираю")
            rootfs.unlink()
        spec = manifest["rootfs"]
        archive = target / "rootfs.ext4.gz"
        if not matches(archive, spec["size"], spec["sha256"]):
            print("MIDI: joining rootfs parts…")
            join_parts(manifest, archive)
        print("MIDI: unpacking rootfs.ext4…")
        gunzip(archive, rootfs)
        archive.unlink()

    if not is_ext4(data):
        spec = manifest["data"]
        src = ASSETS / spec["file"]
        if not matches(src, spec["size"], spec["sha256"]):
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
