"""newc cpio + gzip initramfs builder (Windows QEMU has no 9p)."""
from __future__ import annotations

import gzip
import io
import os
import stat as statmod
from pathlib import Path


def record(name: str, data: bytes, mode: int, ino: int, nlink: int = 1) -> bytes:
    header = (
        "070701"
        + f"{ino:08x}"
        + f"{mode:08x}"
        + f"{0:08x}"
        + f"{0:08x}"
        + f"{nlink:08x}"
        + f"{0:08x}"
        + f"{len(data):08x}"
        + f"{0:08x}"
        + f"{0:08x}"
        + f"{0:08x}"
        + f"{0:08x}"
        + f"{len(name) + 1:08x}"
        + f"{0:08x}"
    ).encode()
    out = header + name.encode() + b"\0"
    out += b"\0" * (-len(out) % 4)
    out += data
    out += b"\0" * (-len(out) % 4)
    return out


def collect(root: Path, meta: dict[str, dict] | None = None) -> list[tuple[str, bytes, int]]:
    """Walk ``root``; ``meta`` restores modes/symlinks lost on Windows."""
    meta = meta or {}
    dirs: list[str] = []
    files: list[tuple[str, bytes, int]] = []

    def walk(directory: Path) -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            name = entry.relative_to(root).as_posix()
            info = meta.get(name, {})
            kind = info.get("type")
            st = entry.lstat()
            if kind == "symlink" or (kind is None and statmod.S_ISLNK(st.st_mode)):
                link = info.get("linkname") or os.readlink(entry)
                files.append((name, link.encode(), 0o120777))
            elif kind == "dir" or (kind is None and statmod.S_ISDIR(st.st_mode)):
                dirs.append(name)
                walk(entry)
            elif kind == "file" or statmod.S_ISREG(st.st_mode):
                mode = info.get("mode")
                if mode is None:
                    mode = st.st_mode
                files.append((name, entry.read_bytes(), 0o100000 | (mode & 0o777)))
    walk(root)
    dirs.sort(key=lambda s: (s.count("/"), s))
    return [("", b"", 0o40755)] + [(d, b"", 0o40755) for d in dirs] + files


def build_initramfs(
    root: Path,
    overlay: dict[str, tuple[bytes, int]],
    out: Path,
    meta: dict[str, dict] | None = None,
) -> int:
    """Pack ``root`` plus overlay entries into a gzip-compressed newc cpio."""
    entries = collect(root, meta)
    by_name: dict[str, tuple[bytes, int]] = {n: (d, m) for n, d, m in entries}
    for name, (data, mode) in overlay.items():
        if mode & 0o170000 == 0:
            mode = 0o100000 | mode
        by_name[name] = (data, mode)

    names = [n for n in by_name if n]
    dirs = sorted(
        (n for n in names if by_name[n][1] & 0o170000 == 0o040000),
        key=lambda s: (s.count("/"), s),
    )
    files = sorted(n for n in names if by_name[n][1] & 0o170000 != 0o040000)

    buf = io.BytesIO()
    ino = 100
    for name in [""] + dirs + files:
        data, mode = by_name[name]
        ino += 1
        buf.write(record(name or ".", data, mode, ino))
    trailer = bytearray(b"070701" + b"00000000" * 13)
    trailer[94:102] = b"0000000b"
    buf.write(bytes(trailer) + b"TRAILER!!!\0")
    buf.write(b"\0" * (-buf.tell() % 4))

    payload = gzip.compress(buf.getvalue(), 6)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(payload)
    return len(files)
