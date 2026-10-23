#!/bin/sh
# Runs inside the original Mini 2 rootfs, using the guest kernel's ARM32 ABI.
set -u
export PATH=/system/vendor/quasar:/usr/bin:/usr/sbin:/bin:/sbin
export LD_LIBRARY_PATH=/system/vendor/quasar/libs:/system/vendor/quasar
export CA_CERTIFICATES=/system/vendor/quasar/ca-certificates.crt
export GST_PLUGIN_PATH=/system/vendor/quasar/libs
mkdir -p /tmp/dbus /var/run/dbus /var/lib/dbus /data/quasar/logs /data/quasar/data /data/quasar/daemons_logs /tmp/quasar
dbus-uuidgen --ensure
dbus-daemon --system --fork
if [ -x /tmp/mic_relay ]; then
    /tmp/mic_relay >/tmp/mic-relay.log 2>&1 &
    echo $! >/tmp/mic-relay.pid
    sleep 1
fi
if [ -x /tmp/pem_proxy ] && [ -f /tmp/private.pem ] && [ -f /tmp/public.pem ]; then
    /tmp/pem_proxy /tmp/private.pem /tmp/public.pem /dev/keymaster_svc >/tmp/pem-proxy.log 2>&1 &
    echo $! >/tmp/pem-proxy.pid
fi
if [ -x /emulator/btvirt ]; then
    /emulator/btvirt -l1 >/tmp/btvirt.log 2>&1 &
    sleep 1
fi
# Firmware connects to the real local D-Bus services, even without radio hardware.
if [ -x /usr/libexec/bluetooth/bluetoothd ]; then
    /usr/libexec/bluetooth/bluetoothd > /tmp/bluetoothd.log 2>&1 &
elif [ -x /usr/lib/bluetooth/bluetoothd ]; then
    /usr/lib/bluetooth/bluetoothd > /tmp/bluetoothd.log 2>&1 &
fi
# Opening the softvol PCM creates the Master mixer control used by platformd.
/usr/bin/aplay -q -D mini2_playback -f S16_LE -c 2 -r 48000 -d 1 /dev/zero >/tmp/audio-init.log 2>&1
mkdir -p /var/run/wpa_supplicant
/usr/sbin/wpa_supplicant -B -D wired -i wlan0 -c /emulator/wpa-wired.conf -f /tmp/wpa-wired.log
ulimit -n 10240
ulimit -s 1024
cd /data/quasar
exec /system/vendor/quasar/quasar_launcher2 /emulator/launch.json
