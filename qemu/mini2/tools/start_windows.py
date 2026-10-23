#!/usr/bin/env python3
"""Windows port of start.sh: QEMU launcher without 9p and without vmnet.

- console chardev is a TCP socket on 127.0.0.1:19096 (Windows QEMU has no
  reliable AF_UNIX chardev; console.py falls back to this port);
- the Alpine bootstrap comes from the self-contained initramfs built by
  build_boot_windows.py (alpine/initramfs-win.cpio.gz);
- audio uses dsound by default (AUDIO_BACKEND env overrides: wasapi, sdl,
  none, pulse, pipewire on non-Windows hosts);
- the host helper (mic PCM 19093 + PEM/epoch HTTP 19094) replaces
  HardwareBridge.app and is started from here if not already running.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

STAND = Path(__file__).resolve().parents[1]
VIEWER = STAND / "viewer"
RUN = STAND / "run"
ALP = STAND / "alpine"
CONSOLE_PORT = 19096


def notify_viewer(payload: dict) -> None:
    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8765/api/event",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=2).read()
    except OSError:
        pass


def find_qemu() -> str:
    env = os.environ.get("QEMU_BIN")
    if env and Path(env).is_file():
        return env
    exe = "qemu-system-aarch64.exe" if os.name == "nt" else "qemu-system-aarch64"
    found = shutil.which(exe)
    if found:
        return found
    candidates = [
        Path(os.environ.get("QEMU_DIR", "")) / exe,
        Path(r"C:\Program Files\qemu") / exe,
        Path(r"C:\Program Files\qemu64") / exe,
    ]
    for c in candidates:
        if c.is_file():
            return str(c)
    raise SystemExit("Нет qemu-system-aarch64. Установи QEMU (см. setup_windows.ps1) или задай QEMU_BIN")


def alive(pid: int | None) -> bool:
    """Cross-platform liveness check.

    os.kill(pid, 0) is POSIX-only: on Windows CPython maps it to
    GenerateConsoleCtrlEvent/TerminateProcess instead of a probe, so a
    status poll could signal or kill the process. Use the Win32 API there.
    """
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def read_pid(name: str) -> int | None:
    try:
        return int((RUN / name).read_text().strip())
    except (OSError, ValueError):
        return None


def spawn_detached(cmd: list[str], log: Path) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab", buffering=0)
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def ensure_host_helper() -> None:
    pid = read_pid("host-helper.pid")
    if alive(pid):
        return
    proc = spawn_detached([sys.executable, str(STAND / "tools" / "host_helper.py")], RUN / "host-helper.log")
    (RUN / "host-helper.pid").write_text(str(proc.pid))


def ensure_hardware_rpc() -> None:
    # BLE GATT bridge backend (loopback-only, same role as on macOS).
    # NOTE: do not gate this on run/hardware.json — the host helper creates
    # that file at startup, before this check runs.
    if os.environ.get("MINI2_DISABLE_BLE"):
        return
    pid = read_pid("hardware-rpc.pid")
    if alive(pid):
        return
    proc = spawn_detached([sys.executable, str(STAND / "tools" / "hardware_rpc.py")], RUN / "hardware-rpc.log")
    (RUN / "hardware-rpc.pid").write_text(str(proc.pid))


def main() -> int:
    qemu = find_qemu()
    initrd = ALP / "initramfs-win.cpio.gz"
    if not initrd.is_file():
        raise SystemExit(f"Нет {initrd} — запусти build_boot_windows.py (см. setup_windows.ps1)")
    kernel = ALP / ("vmlinuz-lts" if (ALP / "vmlinuz-lts").is_file() else "vmlinuz-virt")
    disk = STAND / "mini2-backup.ext4"
    if not disk.is_file():
        raise SystemExit("Нет mini2-backup.ext4 — распакуй runtime")

    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "start.pid").write_text(str(os.getpid()))
    serial_log = RUN / "console.log"
    serial_log.write_text("")

    ensure_host_helper()
    ensure_hardware_rpc()
    notify_viewer({"state": "qemu", "up": True, "message": "QEMU starting"})

    audio_backend = os.environ.get("AUDIO_BACKEND") or ("dsound" if os.name == "nt" else "none")

    args = [
        qemu,
        "-M", "virt",
        "-cpu", "cortex-a53",
        "-smp", "4",
        "-m", os.environ.get("VM_RAM", "1024"),
        "-display", "none",
        "-chardev", f"socket,id=console,host=127.0.0.1,port={CONSOLE_PORT},server=on,wait=off,logfile={serial_log}",
        "-serial", "chardev:console",
        "-monitor", "none",
        "-kernel", str(kernel),
        "-initrd", str(initrd),
        "-append", "console=ttyAMA0 earlyprintk=serial root=/dev/root rw",
        "-netdev", "user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:8443-:443",
        "-device", "virtio-net-device,netdev=n0,mac=52:54:00:4d:32:01",
        "-drive", f"file={disk},format=raw,if=none,id=firmware",
        "-device", "virtio-blk-pci,drive=firmware",
        "-rtc", "base=utc,clock=host",
    ]
    nv = STAND / ".." / ".." / "firmware" / "backups" / "yandex-mini2-backup" / "mtd" / "mtd4_nv.bin"
    if nv.is_file():
        args += [
            "-drive", f"file={nv},format=raw,if=none,id=nv,readonly=on",
            "-device", "virtio-blk-pci,drive=nv",
        ]
    args += [
        "-audiodev", f"{audio_backend},id=audio,out.frequency=48000",
        "-device", "virtio-sound-pci,audiodev=audio",
    ]

    print(f"QEMU headless · console → {serial_log} (TCP 127.0.0.1:{CONSOLE_PORT})")
    print("SSH host:2222 · viewer http://127.0.0.1:8765/")
    print(f"initrd: {initrd.name} · audio: {audio_backend}")

    tail = spawn_detached([sys.executable, str(VIEWER / "console_tail.py"), str(serial_log)], RUN / "console_tail.log")
    (RUN / "console_tail.pid").write_text(str(tail.pid))

    try:
        proc = subprocess.Popen(args, stdout=open(RUN / "qemu-stdout.log", "ab"), stderr=subprocess.STDOUT)
    except OSError as e:
        raise SystemExit(f"QEMU failed to start: {e}")
    (RUN / "qemu.pid").write_text(str(proc.pid))
    notify_viewer({"state": "qemu", "up": True, "message": f"QEMU pid {proc.pid}"})
    try:
        return proc.wait()
    finally:
        notify_viewer({"state": "qemu", "up": False, "message": "QEMU stopped"})
        for name in ("qemu.pid", "start.pid", "console_tail.pid"):
            try:
                (RUN / name).unlink()
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
