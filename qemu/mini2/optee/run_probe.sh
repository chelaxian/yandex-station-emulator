#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/run"
cd "$DIR/run"
TF="$DIR/trusted-firmware-a/build/qemu/release"
TEE="$DIR/optee_os/out/arm-plat-vexpress/core"
for name in bl1 bl2 bl31; do ln -sf "$TF/$name.bin" "$name.bin"; done
ln -sf "$TEE/tee-header_v2.bin" bl32.bin
ln -sf "$TEE/tee-pager_v2.bin" bl32_extra1.bin
ln -sf "$TEE/tee-pageable_v2.bin" bl32_extra2.bin
ARGS=(-machine virt,secure=on -cpu cortex-a53 -smp 4 -m 1024 -display none -monitor none
  -bios "$TF/bl1.bin" -semihosting-config enable=on,target=native
  -fsdev "local,id=alpine,path=$DIR/../alpine_root,security_model=none,readonly=on"
  -device virtio-9p-pci,fsdev=alpine,mount_tag=alpine)
if [[ -f "$DIR/probe.ext4" ]]; then
  ARGS+=(-drive "file=$DIR/probe.ext4,format=raw,if=none,id=firmware" -device virtio-blk-pci,drive=firmware)
fi
NV="${NV_IMAGE:-$DIR/../../../firmware/backups/yandex-mini2-backup/mtd/mtd4_nv.bin}"
ARGS+=(-drive "file=$NV,format=raw,if=none,id=nv,readonly=on" -device virtio-blk-pci,drive=nv)
qemu-system-aarch64 "${ARGS[@]}" -machine "dumpdtb=$DIR/run/probe.dtb"
fdtput -p -t s probe.dtb /chosen bootargs 'console=ttyAMA0 earlycon=pl011,0x9000000 rdinit=/init'
fdtput -t x probe.dtb /chosen linux,initrd-start 0 45000000
SIZE=$(stat -f%z "$DIR/probe-initramfs.gz")
END=$(printf '%x' "$((0x45000000+SIZE))")
fdtput -t x probe.dtb /chosen linux,initrd-end 0 "$END"
echo $$ > "$DIR/run/probe.pid"
exec qemu-system-aarch64 "${ARGS[@]}" \
  -device "loader,file=$DIR/linux/boot/vmlinuz-6.1.0-53-arm64,addr=0x42200000,force-raw=on" \
  -device "loader,file=$DIR/probe-initramfs.gz,addr=0x45000000,force-raw=on" \
  -dtb "$DIR/run/probe.dtb" \
  -chardev "socket,id=normal,path=$DIR/run/console.sock,server=on,wait=off,logfile=$DIR/run/normal.log" \
  -serial chardev:normal -serial "file:$DIR/run/secure.log"
