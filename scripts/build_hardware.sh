#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP="$DIR/qemu/mini2/HardwareBridge.app"
mkdir -p "$APP/Contents/MacOS"
swiftc "$DIR/qemu/mini2/tools/HardwareBridge.swift" -o "$APP/Contents/MacOS/HardwareBridge" \
  -framework AppKit -framework CoreBluetooth -framework AVFoundation -framework Network
python3 - "$APP" <<'PY'
import plistlib,sys
from pathlib import Path
(Path(sys.argv[1])/'Contents/Info.plist').write_bytes(plistlib.dumps({
'CFBundleIdentifier':'local.yandexalice.hardwarebridge','CFBundleName':'Alice Hardware Bridge',
'CFBundleExecutable':'HardwareBridge','CFBundlePackageType':'APPL','LSUIElement':True,
'NSBluetoothAlwaysUsageDescription':'Передавать настройку Bluetooth в ваш эмулятор Алисы.',
'NSMicrophoneUsageDescription':'Передавать микрофон Mac в ваш эмулятор Алисы.'}))
PY
codesign --force --deep --sign - "$APP"
