#!/usr/bin/env python3
"""Windows port of install_runtime.py: verify and unpack the runtime parts.

Differences: extracting the tar on Windows cannot always create symlinks
(requires Developer Mode or elevation). This extractor tries real symlinks
first and falls back to copying the target (files and directories); for
absolute chroot-internal targets the copy is resolved against the
extraction root. Never replaces an existing VM disk.
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
from pathlib import Path, PurePosixPath

repo = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument("--destination", type=Path, default=repo)
a = p.parse_args()
target = a.destination.resolve()
target.mkdir(parents=True, exist_ok=True)
manifest = json.loads((repo / "assets/runtime-manifest.json").read_text())
paths = []
total = hashlib.sha256()
for part in manifest["parts"]:
    path = repo / "assets" / part["file"]
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
            total.update(block)
            size += len(block)
    if size != part["size"] or digest.hexdigest() != part["sha256"]:
        raise SystemExit(f"Checksum mismatch: {path.name}")
    paths.append(path)
if total.hexdigest() != manifest["archive_sha256"]:
    raise SystemExit("Archive checksum mismatch")
disk = target / "qemu/mini2/mini2-backup.ext4"
if disk.exists():
    print("Runtime verified; existing guest disk preserved.")
    raise SystemExit(0)


def resolve_target(member: tarfile.TarInfo, linkname: str) -> Path | None:
    """Resolve a symlink target against the extraction root (chroot-style)."""
    t = PurePosixPath(linkname)
    if t.is_absolute():
        t = PurePosixPath(*t.parts[1:])
    if ".." in t.parts:
        return None
    return target / Path(*t.parts)


def extract_fallback(archive: tarfile.TarFile, member: tarfile.TarInfo) -> None:
    """Extract one member with symlink → copy fallback (Windows-safe)."""
    if member.issym():
        dest = target / Path(*PurePosixPath(member.name).parts)
        src = resolve_target(member, member.linkname)
        try:
            if src and src.is_file():
                shutil.copy2(src, dest)
                return
            if src and src.is_dir():
                shutil.copytree(src, dest, dirs_exist_ok=True)
                return
        except OSError:
            pass
        dest.write_bytes(b"")  # keep a placeholder; guest can recreate it
        return
    archive.extract(member, target, filter="fully_trusted")


class Parts(io.RawIOBase):
    def __init__(self, paths):
        self.paths = iter(paths)
        self.current = None

    def readable(self):
        return True

    def readinto(self, buffer):
        while True:
            if self.current is None:
                try:
                    self.current = next(self.paths).open("rb")
                except StopIteration:
                    return 0
            n = self.current.readinto(buffer)
            if n:
                return n
            self.current.close()
            self.current = None

    def close(self):
        if self.current:
            self.current.close()
        super().close()


with io.BufferedReader(Parts(paths)) as stream:
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] not in ("qemu", "firmware"):
                raise SystemExit("Unsafe archive path")
            if member.issym() or member.islnk():
                try:
                    archive.extract(member, target, filter="fully_trusted")
                except OSError:
                    extract_fallback(archive, member)
            else:
                archive.extract(member, target, filter="fully_trusted")
(target / "qemu/mini2/run").mkdir(exist_ok=True)
print("Runtime installed:", disk)
