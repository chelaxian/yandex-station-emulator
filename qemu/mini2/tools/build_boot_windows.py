#!/usr/bin/env python3
"""Windows port boot builder.

The macOS stand shares the Alpine bootstrap over QEMU 9p (virtfs). Windows
QEMU builds have no 9p server, so this builder packs the whole alpine_root
into a self-contained initramfs (newc cpio + gzip): the kernel unpacks it
into the rootfs with full POSIX semantics (symlinks, exec bits) and runs
/sbin/init directly. The custom /init does not mount anything.

Reuses the already-deployed runtime files inside alpine_root (mic_relay,
pem_proxy, btvirt, launch.json) and only replaces the host-dependent guest
scripts. Rebuilds only when inputs change (hash manifest in run/).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import stat as statmod
import sys
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
GUEST = STAND / "guest"
ARCHIVE = STAND / "alpine" / "initramfs-win.cpio.gz"
MANIFEST = STAND / "run" / "win-initramfs.json"


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".new")
    tmp.write_bytes(data)
    os.chmod(tmp, mode)
    tmp.replace(path)


def cpio_record(name: str, data: bytes, mode: int, ino: int, nlink: int = 1) -> bytes:
    header = (
        "070701"
        + f"{ino:08x}"       # ino
        + f"{mode:08x}"      # mode
        + f"{0:08x}"         # uid
        + f"{0:08x}"         # gid
        + f"{nlink:08x}"     # nlink
        + f"{0:08x}"         # mtime (0 — reproducible)
        + f"{len(data):08x}"  # filesize
        + f"{0:08x}"         # devmajor
        + f"{0:08x}"         # devminor
        + f"{0:08x}"         # rdevmajor
        + f"{0:08x}"         # rdevminor
        + f"{len(name) + 1:08x}"
        + f"{0:08x}"         # check
    ).encode()
    out = header + name.encode() + b"\0"
    out += b"\0" * (-len(out) % 4)
    out += data
    out += b"\0" * (-len(out) % 4)
    return out


def collect_tree(root: Path, skip: set[str]) -> list[tuple[str, bytes, int]]:
    """Walk alpine_root and return (name, data, mode) newc entries."""
    records: list[tuple[str, bytes, int]] = []
    directories: list[str] = []

    def rel(p: Path) -> str:
        return p.relative_to(root).as_posix()

    # depth-first for deterministic order
    def walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            name = rel(entry)
            if name in skip:
                continue
            st = entry.lstat()
            if statmod.S_ISLNK(st.st_mode):
                records.append((name, os.readlink(entry).encode(), 0o120777))
            elif entry.is_dir():
                directories.append(name)
                walk(entry)
            elif entry.is_file():
                records.append((name, entry.read_bytes(), 0o100000 | (st.st_mode & 0o777)))
            # sockets/pipes/fifos in the tree are skipped — they cannot be
            # meaningful inside an initramfs archive

    walk(root)
    directories.sort(key=lambda s: (s.count("/"), s))
    out: list[tuple[str, bytes, int]] = [("", b"", 0o40755)]  # root entry
    out += [(d, b"", 0o40755) for d in directories]
    out += records
    return out


def build() -> None:
    alpine_root = STAND / "alpine_root"
    if not (alpine_root / "bin").is_dir():
        raise SystemExit("Нет alpine_root — сначала распакуй runtime (install_runtime)")
    backup_ext4 = STAND / "mini2-backup.ext4"
    if not backup_ext4.is_file():
        raise SystemExit("Нет mini2-backup.ext4 — Windows-порт требует диск прошивки из runtime")

    # guest scripts deployed by this builder (everything else stays as shipped)
    deploy = {
        "etc/local.d/mini2.start": (GUEST / "mini2-windows.start", 0o755),
        "opt/mini2/status.sh": (GUEST / "status.sh", 0o755),
        "init": (GUEST / "init-windows", 0o755),
    }
    for target, (source, _) in deploy.items():
        if not source.is_file():
            raise SystemExit(f"Нет {source}")

    # inputs hash → skip rebuild when nothing changed
    h = hashlib.sha256()
    for source, _ in deploy.values():
        h.update(source.read_bytes())
    total_files = 0
    total_bytes = 0
    for path in sorted(alpine_root.rglob("*")):
        try:
            st = path.lstat()
        except OSError:
            continue
        total_files += 1
        total_bytes += st.st_size
        h.update(str(path.relative_to(alpine_root)).encode())
        h.update(str(st.st_mode).encode())
        if not path.is_dir():
            try:
                h.update(b"L" + os.readlink(path).encode()) if path.is_symlink() else None
            except OSError:
                pass
            if path.is_file():
                h.update(hashlib.sha256(path.read_bytes()).digest())
    inputs_digest = h.hexdigest()
    if ARCHIVE.is_file() and MANIFEST.is_file():
        try:
            if json.loads(MANIFEST.read_text()).get("inputs_sha256") == inputs_digest:
                print(f"initramfs up to date: {ARCHIVE}")
                return
        except ValueError:
            pass

    print(f"packing alpine_root → {ARCHIVE.name} ({total_files} entries, {total_bytes/1e6:.1f} MB)…")
    entries = collect_tree(alpine_root, skip=set())
    name_to_entry = {name: (data, mode) for name, data, mode in entries}

    # overlay guest scripts
    for target, (source, mode) in deploy.items():
        name_to_entry[target] = (source.read_bytes(), 0o100000 | mode)

    # deterministic ordering: root, directories, then files
    dirs = sorted((n for n in name_to_entry if n and name_to_entry[n][1] & 0o170000 == 0o040000),
                  key=lambda s: (s.count("/"), s))
    files = sorted((n for n in name_to_entry if n and name_to_entry[n][1] & 0o170000 != 0o040000))

    out = io.BytesIO()
    ino = 100
    for name in [""] + dirs + files:
        data, mode = name_to_entry[name]
        ino += 1
        out.write(cpio_record(name or ".", data, mode, ino))
    trailer = bytearray(b"070701" + b"00000000" * 13)
    trailer[94:102] = b"0000000b"
    out.write(bytes(trailer) + b"TRAILER!!!\0")
    out.write(b"\0" * (-out.tell() % 4))

    payload = gzip.compress(out.getvalue(), 6)
    atomic_write(ARCHIVE, payload, 0o644)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({
        "inputs_sha256": inputs_digest,
        "archive": str(ARCHIVE),
        "size": len(payload),
        "entries": total_files,
    }, indent=2))
    print(f"Built {ARCHIVE} ({len(payload)/1e6:.1f} MB compressed)")


if __name__ == "__main__":
    build()
