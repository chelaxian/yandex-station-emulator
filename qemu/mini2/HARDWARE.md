# Host hardware bridges

`HardwareBridge.app` uses macOS CoreBluetooth and AVAudioEngine. Its permission
requests are for Bluetooth and microphone access. Live status is run/hardware.json.

## LAN

`sudo bash tools/enable_lan.sh` starts a network-only privileged QEMU process.
It connects en0 through vmnet to run/vmnet.sock. The main VM remains under the
normal user account. start.sh detects the helper and selects the stream backend.
The firmware-facing NIC has MAC 52:54:00:4d:32:01; a separate NAT NIC ending in
:02 carries host microphone traffic to 10.0.2.2. NICs are identified by MAC,
not Linux enumeration order. guest/lan-dhcp.sh applies the LAN DHCP lease.

Verified lease: 172.16.62.104/16, gateway 172.16.1.10. Ping and HTTPS passed.
This is Ethernet bridging through the Mac's Wi-Fi connection, not a guest
Wi-Fi radio. Firmware Wi-Fi scanning/association is still the wired shim.

## Bluetooth

tools/hardware_rpc.py listens only at 127.0.0.1:19092 and forwards GATT operations
to the actual ru.yandex.quasar D-Bus objects in the VM. Reads, writes and status
notifications map to the firmware's service0/char0..5. Writes use temporary
mode-0600 files, keeping credentials out of serial command echo. Serial RPC calls
are serialized. The native app advertises service UUID
664578b6-c390-42d8-956e-c1ae8b646436 and the real device name.

macOS confirms advertising, and guest device-ID/status reads pass. However,
the user's Yandex app does not discover the bridge. The firmware advertisement
also contains ManufacturerData {2309: [04,4b]}. Public CoreBluetooth advertising
supports only local name and service UUIDs, so this bridge cannot reproduce the
complete native advertisement. A raw USB BLE controller would avoid this limit;
the user currently has none. Do not label phone onboarding ready.

## Microphone

The native app captures and converts microphone input to stereo S16_LE at 48kHz,
and streams it over a loopback-only TCP listener on port 19093. The guest
tools/mic_relay.c pulls this into /tmp/mac-microphone.pcm. ALSA file/plug capture
adapts it to the firmware's six-channel interface. Startup copies the receiver
to guest RAM and starts it automatically; the original QEMU CoreAudio backend
still handles playback only.

Verified: native microphone RMS is nonzero; six-channel arecord completes;
a 4096-sample guest check measured RMS 80.6844. Test recordings were deleted.
This validates host-to-guest transport, not voice activation or acoustic pairing.
Firmware capture now works after emulating GPIO 414 and 419 under its sysfs.
Without 414, audio setup stopped before ALSA capture; providing only 414 exposed
a fatal missing GPIO 419. Both interfaces are now provided at boot. The actual
platformd process opens /tmp/mac-microphone.pcm and continuously consumes PCM.
The stock sound_initd receiver is active in init mode 1 with 320-sample frames.
The first user acoustic test preceded this fix and decoded no packet. A repeat
test has been requested. Temporary audio tracing and WebSocket experiments have
been removed from the generated launch configuration.

PEM keys stay in guest RAM; temporary host staging files are deleted after boot.
Their local export/sign/decrypt adapter works with the stock client. Cloud
authorization and app onboarding remain unverified.
