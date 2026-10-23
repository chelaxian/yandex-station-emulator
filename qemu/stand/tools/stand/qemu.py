"""QEMU process controller shared by both models."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import config


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_qemu() -> str:
    env = os.environ.get("QEMU_BIN")
    if env and Path(env).is_file():
        return env
    exe = "qemu-system-aarch64.exe" if os.name == "nt" else "qemu-system-aarch64"
    for base in (
        config.REPO / "qemu-win",
        Path("C:/Program Files/qemu"),
        Path("C:/Program Files/qemu64"),
    ):
        candidate = (base / exe).resolve()
        if candidate.is_file():
            return str(candidate)
    found = shutil_which(exe)
    if found:
        return found
    raise SystemExit("QEMU not found: set QEMU_BIN or install QEMU")


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


class Stand:
    def __init__(self, model: str, audio: str | None = None, console_port: int = 19096, qemu: str | None = None):
        self.model = config.model(model)
        self.audio = audio or os.environ.get("AUDIO_BACKEND") or self.model["audio"]
        self.console_port = console_port
        self.qemu = qemu or find_qemu()
        self.run_dir = config.ROOT / "run" / self.model["id"]
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.console_log = self.run_dir / "console.log"
        self.proc: subprocess.Popen | None = None

    # -- command line -----------------------------------------------------
    def args(self) -> list[str]:
        m = self.model
        a = [
            self.qemu,
            "-M", "virt",
            "-cpu", m["cpu"],
            "-smp", "4",
            "-m", str(m["memory"]),
            "-display", "none",
            "-chardev",
            f"socket,id=console,host=127.0.0.1,port={self.console_port},server=on,wait=off,"
            f"logfile={self.console_log}",
            "-serial", "chardev:console",
            "-monitor", "none",
            "-kernel", str(m["kernel"]),
            "-initrd", str(m["initrd"]),
            "-append", "console=ttyAMA0 earlyprintk=serial root=/dev/root rw",
            "-netdev", "user,id=n0",
            "-device", "virtio-net-device,netdev=n0,mac=52:54:00:4d:32:01",
        ]
        for ident, path, read_only in m["disks"]:
            opt = f"file={path},format=raw,if=none,id={ident}"
            if read_only:
                opt += ",readonly=on"
            a += ["-drive", opt, "-device", f"virtio-blk-pci,drive={ident}"]
        if m.get("nv"):
            a += [
                "-drive", f"file={m['nv']},format=raw,if=none,id=nv,readonly=on",
                "-device", "virtio-blk-pci,drive=nv",
            ]
        a += ["-rtc", "base=utc,clock=host"]
        a += ["-audiodev", f"{self.audio},id=audio", "-device", "virtio-sound-pci,audiodev=audio"]
        return a

    # -- lifecycle --------------------------------------------------------
    def start(self, detached: bool = True) -> subprocess.Popen:
        if self.proc and self.proc.poll() is None:
            return self.proc
        if _alive(self._pid()):
            raise RuntimeError("already running")
        self.console_log.write_text("")
        out = open(self.run_dir / "qemu-stdout.log", "ab", buffering=0)
        kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(self.args(), **kwargs)
        (self.run_dir / "qemu.pid").write_text(str(self.proc.pid))
        return self.proc

    def _pid(self) -> int | None:
        try:
            return int((self.run_dir / "qemu.pid").read_text().strip())
        except (OSError, ValueError):
            return None

    def alive(self) -> bool:
        if self.proc and self.proc.poll() is None:
            return True
        pid = self._pid()
        if not _alive(pid):
            return False
        self.proc = None
        return True

    def pid(self) -> int | None:
        pid = self._pid()
        return pid if _alive(pid) else None

    def stop(self) -> None:
        pid = self.pid()
        if pid:
            try:
                if os.name == "nt":
                    import subprocess as sp

                    sp.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=8)
                else:
                    os.kill(pid, 15)
            except (OSError, Exception):
                pass
        for _ in range(30):
            if not _alive(pid):
                break
            time.sleep(0.1)
        self.proc = None
        try:
            (self.run_dir / "qemu.pid").unlink()
        except OSError:
            pass

    def reboot(self) -> None:
        self.stop()
        self.start()

    def status(self) -> dict:
        return {
            "model": self.model["id"],
            "title": self.model["title"],
            "up": self.alive(),
            "pid": self.pid(),
            "console": str(self.console_log),
            "audio": self.audio,
        }


def wait(stand: Stand) -> int:
    proc = stand.start()
    try:
        return proc.wait()
    except KeyboardInterrupt:
        stand.stop()
        return 130


if __name__ == "__main__":
    sys.exit(wait(Stand(os.environ.get("MODEL", "mini"))))
