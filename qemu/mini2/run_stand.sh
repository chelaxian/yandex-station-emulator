#!/usr/bin/env bash
# Viewer + LED + QEMU. Демоны через tools/daemonize.py (start_new_session, macOS).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
RUN="$DIR/run"
mkdir -p "$RUN" "$DIR/led_sysfs"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:${PATH:-}"
PY=/usr/bin/python3
DAEMON=("$PY" "$DIR/tools/daemonize.py")

MY=$$
for p in $(pgrep -f "$DIR/run_stand.sh" 2>/dev/null || true); do
  if [[ "$p" != "$MY" ]]; then kill "$p" 2>/dev/null || true; fi
done

pkill -f "$DIR/viewer/server.py" 2>/dev/null || true
pkill -f "$DIR/viewer/led_bridge.py" 2>/dev/null || true
pkill -f "$DIR/tools/alice_leds.py" 2>/dev/null || true
pkill -f "$RUN/watchdog.sh" 2>/dev/null || true
for p in $(lsof -t -nP -iTCP:8765 -sTCP:LISTEN 2>/dev/null || true); do
  kill "$p" 2>/dev/null || true
done
sleep 1

"$PY" "$DIR/tools/mk_led_sysfs.py" --out "$DIR/led_sysfs" >/dev/null

echo "[stand] viewer"
"${DAEMON[@]}" "$RUN/viewer.pid" "$RUN/viewer.log" -- \
  "$PY" "$DIR/viewer/server.py"

ok=0
for _ in $(seq 1 40); do
  if curl -sf -m 1 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 0.25
done
if [[ "$ok" != 1 ]]; then
  echo "[stand] viewer FAILED" >&2
  tail -40 "$RUN/viewer.log" >&2 || true
  exit 1
fi

echo "[stand] leds"
"${DAEMON[@]}" "$RUN/led_bridge.pid" "$RUN/led_bridge.log" -- \
  "$PY" "$DIR/viewer/led_bridge.py" "$DIR/led_sysfs"
if [[ ! -f "$DIR/mini2-backup.ext4" ]]; then
  "${DAEMON[@]}" "$RUN/alice_leds.pid" "$RUN/alice_leds.log" -- \
    "$PY" "$DIR/tools/alice_leds.py" --sysfs "$DIR/led_sysfs" clock
fi

UP=$(curl -sf -m 2 http://127.0.0.1:8765/api/qemu | "$PY" -c 'import sys,json; print(json.load(sys.stdin).get("up"))' 2>/dev/null || echo False)
if [[ "$UP" != "True" && "$UP" != "true" ]]; then
  echo "[stand] qemu boot"
  curl -sf -m 45 -X POST http://127.0.0.1:8765/api/qemu \
    -H 'content-type: application/json' -d '{"action":"boot"}' || true
  echo
else
  echo "[stand] qemu already up"
fi

cat >"$RUN/watchdog.sh" <<EOF
#!/usr/bin/env bash
DIR="$DIR"
RUN="\$DIR/run"
PY=/usr/bin/python3
DAEMON=("\$PY" "\$DIR/tools/daemonize.py")
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:\${PATH:-}"
while true; do
  sleep 4
  if ! curl -sf -m 1 http://127.0.0.1:8765/api/health >/dev/null 2>&1; then
    echo "[watch] viewer \$(date +%H:%M:%S)" >>"\$RUN/stand.log"
    pkill -f "\$DIR/viewer/server.py" 2>/dev/null || true
    sleep 0.4
    "\${DAEMON[@]}" "\$RUN/viewer.pid" "\$RUN/viewer.log" -- "\$PY" "\$DIR/viewer/server.py"
  fi
  if ! pgrep -f "\$DIR/viewer/led_bridge.py" >/dev/null 2>&1; then
    "\${DAEMON[@]}" "\$RUN/led_bridge.pid" "\$RUN/led_bridge.log" -- "\$PY" "\$DIR/viewer/led_bridge.py" "\$DIR/led_sysfs"
  fi
  if [[ ! -f "\$DIR/mini2-backup.ext4" ]] && ! pgrep -f "\$DIR/tools/alice_leds.py" >/dev/null 2>&1; then
    "\${DAEMON[@]}" "\$RUN/alice_leds.pid" "\$RUN/alice_leds.log" -- "\$PY" "\$DIR/tools/alice_leds.py" --sysfs "\$DIR/led_sysfs" clock
  fi
done
EOF
chmod +x "$RUN/watchdog.sh"
"${DAEMON[@]}" "$RUN/watchdog.pid" "$RUN/stand.log" -- bash "$RUN/watchdog.sh"

echo "[stand] OK → http://127.0.0.1:8765/"
curl -sf -m 2 http://127.0.0.1:8765/api/health; echo
curl -sf -m 2 -o /dev/null -w "web:%{http_code}\n" http://127.0.0.1:8765/
echo "viewer=$(cat "$RUN/viewer.pid") watchdog=$(cat "$RUN/watchdog.pid")"
