"""Model definitions for the Yandex Station emulator stand."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # qemu/stand
REPO = ROOT.parents[1]                       # repository root
MINI2 = REPO / "qemu" / "mini2"
DATA = ROOT / "data"

MODELS: dict[str, dict] = {
    "mini": {
        "id": "mini",
        "title": "Яндекс Станция Мини 2",
        "short": "Мини 2",
        "cpu": "cortex-a53",
        "memory": 1024,
        "kernel": MINI2 / "alpine" / "vmlinuz-lts",
        "initrd": MINI2 / "alpine" / "initramfs-win.cpio.gz",
        "disks": [("firmware", MINI2 / "mini2-backup.ext4", False)],
        "nv": REPO / "firmware" / "backups" / "yandex-mini2-backup" / "mtd" / "mtd4_nv.bin",
        "audio": "dsound",
        "guest": "mini2",
    },
    "midi": {
        "id": "midi",
        "title": "Яндекс Станция Миди",
        "short": "Миди",
        "cpu": "cortex-a55",
        "memory": 1024,
        "kernel": MINI2 / "alpine" / "vmlinuz-lts",
        "initrd": DATA / "midi" / "initramfs-midi.cpio.gz",
        "disks": [
            ("rootfs", DATA / "midi" / "rootfs.ext4", False),
            ("data", DATA / "midi" / "data.ext4", False),
        ],
        "nv": None,
        "audio": "dsound",
        "guest": "midi",
    },
}


def model(name: str) -> dict:
    try:
        return MODELS[name]
    except KeyError:
        raise SystemExit(f"unknown model: {name} (available: {', '.join(MODELS)})") from None


def missing(model_def: dict) -> list[Path]:
    files = [model_def["kernel"], model_def["initrd"]]
    files += [path for _, path, _ in model_def["disks"]]
    if model_def.get("nv"):
        files.append(model_def["nv"])
    return [p for p in files if not p.is_file()]
