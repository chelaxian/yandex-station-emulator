#!/bin/sh
alive() {
    pid=$(cat "/mini2/tmp/run/$1.pid" 2>/dev/null || true)
    if [ -n "$pid" ] && [ -r "/proc/$pid/cmdline" ] && tr '\000' ' ' <"/proc/$pid/cmdline" | grep -q -- "--$1"; then
        printf true
    else
        printf false
    fi
}
while true; do
    platform=$(alive platformd)
    media=$(alive mediad)
    telemetry=$(alive telemetry)
    sound=false; [ -c /dev/snd/pcmC0D0p ] && sound=true
    keys=false
    if [ -c /dev/tee0 ] && [ -S /mini2/dev/keymaster_svc ] && pidof keymaster_svc >/dev/null; then
        keys=true
    fi
    bluetooth=false; [ -e /sys/class/bluetooth/hci0 ] && bluetooth=true
    network=false; ip route | grep -q '^default ' && network=true
    printf '{"source":"backup","platformd":%s,"mediad":%s,"telemetry":%s,"sound":%s,"keymaster":%s,"bluetooth":%s,"network":%s,"timestamp":%s}\n' \
        "$platform" "$media" "$telemetry" "$sound" "$keys" "$bluetooth" "$network" "$(date +%s)" >/mnt/leds/.firmware-status.tmp
    mv /mnt/leds/.firmware-status.tmp /mnt/leds/.firmware-status.json
    sleep 5
done
