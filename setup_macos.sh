#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
[[ $(uname -s) == Darwin && $(uname -m) == arm64 ]] || { echo 'Requires an Apple Silicon Mac.' >&2;exit 1; }
[[ $EUID != 0 ]] || { echo 'Run setup as your normal user, without sudo.' >&2;exit 1; }
if ! xcode-select -p >/dev/null 2>&1; then
  xcode-select --install
  echo 'Finish Command Line Tools installation, then run setup again.';exit 1
fi
if ! command -v brew >/dev/null; then
  echo 'Install Homebrew from https://brew.sh, then run this script again.';exit 1
fi
HOMEBREW_NO_AUTO_UPDATE=1 brew install qemu python@3.12
PY="$(brew --prefix python@3.12)/bin/python3.12"
"$PY" scripts/install_runtime.py
mkdir -p qemu/mini2/run qemu/mini2/led_sysfs
chmod 600 keys/private.pem keys/public.pem
openssl pkey -in keys/private.pem -pubout -out qemu/mini2/run/derived-public.pem >/dev/null 2>&1
openssl pkey -pubin -in keys/public.pem -outform DER -out qemu/mini2/run/public.der >/dev/null 2>&1
openssl pkey -pubin -in qemu/mini2/run/derived-public.pem -outform DER -out qemu/mini2/run/derived.der >/dev/null 2>&1
cmp qemu/mini2/run/public.der qemu/mini2/run/derived.der
rm qemu/mini2/run/derived-public.pem qemu/mini2/run/public.der qemu/mini2/run/derived.der
bash scripts/build_hardware.sh
"$PY" qemu/mini2/tools/mk_led_sysfs.py --out qemu/mini2/led_sysfs >/dev/null
echo 'Setup complete. Starting the stand...'
bash qemu/mini2/run_stand.sh
open http://127.0.0.1:8765/
