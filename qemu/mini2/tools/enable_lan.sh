#!/bin/bash
# Privileged, network-only QEMU process: vmnet <-> local Unix stream.
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [[ $EUID != 0 ]]; then echo "Run: sudo bash '$0'" >&2; exit 1; fi
OWNER="${SUDO_UID:-$(stat -f%u "$DIR")}"
SOCKET="$DIR/run/vmnet.sock"
if [[ -f "$DIR/run/vmnet.pid" ]] && kill -0 "$(cat "$DIR/run/vmnet.pid")" 2>/dev/null; then
  echo 'LAN helper already running';exit 0
fi
rm -f "$SOCKET"
nohup /opt/homebrew/bin/qemu-system-aarch64 -machine none -nodefaults -display none -monitor none -serial none \
  -netdev vmnet-bridged,id=lan,ifname=en0 \
  -netdev "stream,id=guest,server=on,addr.type=unix,addr.path=$SOCKET" \
  -netdev hubport,id=lanport,hubid=0,netdev=lan \
  -netdev hubport,id=guestport,hubid=0,netdev=guest \
  >"$DIR/run/vmnet.log" 2>&1 </dev/null &
PID=$!;echo "$PID" >"$DIR/run/vmnet.pid"
for ((i=0;i<50;i++)); do
  if ! kill -0 "$PID" 2>/dev/null; then cat "$DIR/run/vmnet.log";exit 1;fi
  if [[ -S "$SOCKET" ]]; then chown "$OWNER" "$SOCKET";chmod 600 "$SOCKET";echo 'LAN bridge ready. Reboot the emulator.';exit 0;fi
  sleep .1
done
echo 'Network helper did not create its socket';exit 1
