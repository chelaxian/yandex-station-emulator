#!/usr/bin/env bash
# Mini 2 stand: Alpine virt + 9p (alpine_root + mini2 rootfs)
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
ALP="$DIR/alpine"
ALP_ROOT="$DIR/alpine_root"
ROOTFS="$DIR/rootfs_files"
VIEWER="$DIR/viewer"

QEMU="${QEMU:-qemu-system-aarch64}"
if ! command -v "$QEMU" >/dev/null; then
  echo "Нет $QEMU. brew install qemu" >&2
  exit 1
fi
if [[ ! -f "$ALP/vmlinuz-virt" ]]; then
  echo "Нет $ALP/vmlinuz-virt" >&2
  exit 1
fi
if [[ ! -f "$DIR/mini2-backup.ext4" && ! -d "$ROOTFS/bin" ]]; then
  echo "Нет rootfs_files — распакуй дамп" >&2
  exit 1
fi

# предпочитаем свой initramfs (9p → alpine_root), иначе сток Alpine
INITRD="$ALP/initramfs-9p.cpio.gz"
if [[ ! -f "$INITRD" ]]; then
  INITRD="$ALP/initramfs-virt"
fi
if [[ ! -d "$ALP_ROOT/bin" ]]; then
  echo "Нет alpine_root — будет emergency shell Alpine" >&2
fi

# сигнал вьюеру
notify_viewer() {
  curl -sS -m 2 -X POST "http://127.0.0.1:8765/api/event" \
    -H 'content-type: application/json' \
    -d "$1" >/dev/null 2>&1 || true
}

# pid-файл для /api/qemu
mkdir -p "$DIR/run"
echo $$ > "$DIR/run/start.pid"
if [[ -d "$DIR/HardwareBridge.app" ]]; then
  open -g "$DIR/HardwareBridge.app" --args "$DIR" >/dev/null 2>&1 || true
  RPC_PID=$(cat "$DIR/run/hardware-rpc.pid" 2>/dev/null || true)
  if [[ -z "$RPC_PID" ]] || ! kill -0 "$RPC_PID" 2>/dev/null; then
    python3 "$DIR/tools/daemonize.py" "$DIR/run/hardware-rpc.pid" "$DIR/run/hardware-rpc.log" -- python3 "$DIR/tools/hardware_rpc.py" >/dev/null
  fi
fi
notify_viewer '{"state":"qemu","up":true,"message":"QEMU starting"}'

TAIL_PID=""
cleanup() {
  if [[ -n "${TAIL_PID:-}" ]]; then
    kill "$TAIL_PID" 2>/dev/null || true
  fi
  rm -f "$DIR/run/qemu.pid" "$DIR/run/start.pid" "$DIR/run/console_tail.pid"
  notify_viewer '{"state":"qemu","up":false,"message":"QEMU stopped"}'
}
trap cleanup EXIT

APPEND="console=ttyAMA0 earlyprintk=serial"
if [[ -f "$ALP/initramfs-9p.cpio.gz" && -d "$ALP_ROOT/bin" ]]; then
  APPEND="$APPEND root=/dev/root rw"
else
  APPEND="$APPEND root=/dev/ram0 alpine_repo=https://dl-cdn.alpinelinux.org/alpine/v3.20/main modules=loop,squashfs,sd-mod,usb-storage,virtio_pci,virtio_mmio,virtio_blk,9pnet_virtio,9p"
fi

SERIAL_LOG="$DIR/run/console.log"
mkdir -p "$DIR/run"
: > "$SERIAL_LOG"
mkdir -p "$ALP_ROOT/opt/mini2"
date -u +%s > "$ALP_ROOT/opt/mini2/host_epoch"
PEM_SOURCE="${PEM_SOURCE_DIR:-$DIR/../../keys}"
if [[ -f "$ALP_ROOT/opt/mini2/pem_proxy" && -f "$PEM_SOURCE/private.pem" && -f "$PEM_SOURCE/public.pem" ]]; then
  mkdir -p "$ALP_ROOT/opt/mini2/pem-keys"
  chmod 700 "$ALP_ROOT/opt/mini2/pem-keys"
  install -m 600 "$PEM_SOURCE/private.pem" "$ALP_ROOT/opt/mini2/pem-keys/private.pem"
  install -m 600 "$PEM_SOURCE/public.pem" "$ALP_ROOT/opt/mini2/pem-keys/public.pem"
fi

NETDEV="user,id=n0,hostfwd=tcp:127.0.0.1:2222-:22,hostfwd=tcp:127.0.0.1:8443-:443"
if [[ -S "$DIR/run/vmnet.sock" ]] && [[ -f "$DIR/run/vmnet.pid" ]] && ps -p "$(cat "$DIR/run/vmnet.pid")" -o comm= | grep -q qemu-system-aarch64; then
  NETDEV="stream,id=n0,addr.type=unix,addr.path=$DIR/run/vmnet.sock"
  echo lan > "$ALP_ROOT/opt/mini2/network_mode"
else
  echo nat > "$ALP_ROOT/opt/mini2/network_mode"
fi
ARGS=(
  -M virt
  -cpu cortex-a53
  -smp 4
  -m 1024
  -display none
  -chardev "socket,id=console,path=$DIR/run/console.sock,server=on,wait=off,logfile=$SERIAL_LOG"
  -serial chardev:console
  -monitor none
  -kernel "${KERNEL:-$ALP/$(if [[ -f "$ALP/vmlinuz-lts" ]]; then echo vmlinuz-lts; else echo vmlinuz-virt; fi)}"
  -initrd "$INITRD"
  -append "$APPEND"
  -netdev "$NETDEV"
  -device virtio-net-device,netdev=n0,mac=52:54:00:4d:32:01
)
if [[ "$NETDEV" == stream,* ]]; then
  ARGS+=(-netdev user,id=control -device virtio-net-device,netdev=control,mac=52:54:00:4d:32:02)
fi

# 9p: alpine root (если есть) + mini2 dump
if [[ -d "$ALP_ROOT/bin" ]]; then
  ARGS+=(-fsdev "local,id=alpine,path=$ALP_ROOT,security_model=none")
  ARGS+=(-device virtio-9p-pci,fsdev=alpine,mount_tag=alpine)
fi
if [[ -f "$DIR/mini2-backup.ext4" ]]; then
  ARGS+=(-drive "file=$DIR/mini2-backup.ext4,format=raw,if=none,id=firmware")
  ARGS+=(-device virtio-blk-pci,drive=firmware)
  NV="$DIR/../../firmware/backups/yandex-mini2-backup/mtd/mtd4_nv.bin"
  if [[ -f "$NV" ]]; then
    ARGS+=(-drive "file=$NV,format=raw,if=none,id=nv,readonly=on")
    ARGS+=(-device virtio-blk-pci,drive=nv)
  fi
  ARGS+=(-audiodev "coreaudio,id=audio,out.frequency=48000")
  ARGS+=(-device virtio-sound-pci,audiodev=audio)
else
  ARGS+=(-fsdev "local,id=mini2,path=$ROOTFS,security_model=none")
  ARGS+=(-device virtio-9p-pci,fsdev=mini2,mount_tag=mini2)
fi

# fake /sys/class/leds (IS31) — Алиса/QC пишут brightness → led_bridge → viewer
LED_SYSFS="$DIR/led_sysfs"
if [[ ! -d "$LED_SYSFS"/mini2:red:ring1 ]]; then
  python3 "$DIR/tools/mk_led_sysfs.py" --out "$LED_SYSFS" || true
fi
ARGS+=(-fsdev "local,id=leds,path=$LED_SYSFS,security_model=none")
ARGS+=(-device virtio-9p-pci,fsdev=leds,mount_tag=leds)

echo "QEMU headless · console → $SERIAL_LOG"
echo "SSH host:2222 · viewer http://127.0.0.1:8765/"
echo "initrd: $INITRD"

# serial → viewer (консоль загрузки)
python3 "$VIEWER/console_tail.py" "$SERIAL_LOG" >"$DIR/run/console_tail.log" 2>&1 &
TAIL_PID=$!
echo "$TAIL_PID" > "$DIR/run/console_tail.pid"

"$QEMU" "${ARGS[@]}" "$@" &
QPID=$!
echo "$QPID" > "$DIR/run/qemu.pid"
notify_viewer '{"state":"qemu","up":true,"message":"QEMU pid '"$QPID"'"}'
wait "$QPID"
EC=$?
notify_viewer '{"state":"qemu","up":false,"message":"QEMU exit '"$EC"'"}'
exit "$EC"
