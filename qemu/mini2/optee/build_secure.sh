#!/bin/bash
# Rebuild the isolated secure-world experiment from the downloaded sources.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/../build-venv/bin/python"
TOOLS="$DIR/host-tools/bin"
export PATH="$DIR/../build-venv/bin:$TOOLS:/opt/homebrew/bin:$PATH"
for source in udivti3 udivmodti4; do
  clang --target=aarch64-none-elf -O2 -ffreestanding -fno-stack-protector \
    -c "$DIR/compiler-rt/$source.c" -o "$DIR/compiler-rt/$source.o"
done
llvm-ar rcs "$DIR/compiler-rt/builtins.a" "$DIR/compiler-rt/udivti3.o" "$DIR/compiler-rt/udivmodti4.o"
make -C "$DIR/optee_os" -j6 PLATFORM=vexpress-qemu_armv8a COMPILER=clang \
  CROSS_COMPILE64=aarch64-linux-gnu- CROSS_COMPILE32=arm-linux-gnueabihf- \
  OPTEE_CLANG_COMPILER_PATH="$TOOLS/" CFG_CORE_DYN_SHM=n \
  CFG_BUILD_IN_TREE_TA=n CFG_USER_TA_TARGETS=ta_arm32 \
  libgcccore="$DIR/compiler-rt/builtins.a" libgccldelf= libgccta_arm32= PYTHON3="$PY"
make -C "$DIR/trusted-firmware-a" -j6 PLAT=qemu ARCH=aarch64 \
  CC='clang --target=aarch64-none-elf' LD=ld.lld AR=llvm-ar OC=llvm-objcopy OD=llvm-objdump \
  SPD=opteed BL32_RAM_LOCATION=tdram ARM_LINUX_KERNEL_AS_BL33=1 PRELOADED_BL33_BASE=0x42200000 all
"$PY" - "$DIR" <<'PY'
import sys
from pathlib import Path
r=Path(sys.argv[1])
b=(r.parent/'backup_rootfs_files/lib/teetz/8efb1e1c-37e5-4326-a5d68c33726c7d57.ta').read_bytes()
offset=b.find(b'\x7fELF')
assert offset >= 0
(r/'keymaster-ta.elf').write_bytes(b[offset:])
PY
"$PY" "$DIR/optee_os/scripts/sign_encrypt.py" sign-enc \
  --uuid 8efb1e1c-37e5-4326-a5d6-8c33726c7d57 --in "$DIR/keymaster-ta.elf" \
  --out "$DIR/../alpine_root/opt/mini2/probe-keymaster.ta" --key "$DIR/optee_os/keys/default_ta.pem"
"$PY" "$DIR/build_probe.py"
