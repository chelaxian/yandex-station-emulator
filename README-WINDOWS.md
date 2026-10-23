# Порт на Windows: эмулятор Яндекс Станции Мини 2

Порт стенда [initialfox/yandex-station-emulator](https://github.com/initialfox/yandex-station-emulator)
с macOS (Apple Silicon) на Windows 10/11 x64. Основан на коммите `8369237`.

## Почему это не «просто скрипт»

Вся связка macOS-стенда держится на трёх вещах, которых нет под Windows:

1. **9p/virtfs.** QEMU для Windows не содержит 9p-сервера, а через него
   передаются и Alpine-бутстрап, и фейковый LED-sysfs. Замена: весь
   `alpine_root` пакуется в самодостаточный initramfs (newc cpio) — ядро
   распаковывает его в rootfs с полноценной POSIX-семантикой (symlinks, exec-биты),
   и нужда в 9p отпадает полностью. Сборка: `qemu/mini2/tools/build_boot_windows.py`.
2. **HardwareBridge.swift** (CoreAudio + CoreBluetooth). Замена:
   `tools/host_helper.py` — захват микрофона через sounddevice/WASAPI
   (тот же поток PCM S16LE 48 кГц стерео в TCP 19093, что читает гостевой
   `mic_relay`), выдача PEM-ключей и времени по HTTP 19094 (гость забирает
   их сам с 10.0.2.2 — это шлюз user-mode сети QEMU, виден только изнутри VM).
3. **LED-sysfs через 9p.** Замена: гостевой агент в `mini2-windows.start`
   пишет значения яркости по TCP на 10.0.2.2:19095, хостовый
   `viewer/led_bridge_windows.py` принимает их и кормит панель (логика
   декодирования кольца/часов идентична `led_bridge.py`).

Сериальная консоль QEMU переведена с unix-сокета на TCP 127.0.0.1:19096
(`tools/console.py` умеет оба варианта), звук — на `dsound`
(`AUDIO_BACKEND=wasapi|sdl|none` в переменных окружения).

## Установка

```powershell
git clone https://github.com/initialfox/yandex-station-emulator.git
cd yandex-station-emulator
# скопировать файлы порта поверх репозитория (см. «Состав порта» ниже)
powershell -ExecutionPolicy Bypass -File setup_windows.ps1
```

Скрипт ставит QEMU и Python через winget, проверяет SHA256 всех частей
runtime, распаковывает его (с фолбэком для symlink'ов, если не включён
Developer Mode), собирает Windows-initramfs и запускает стенд.
Нужно ~4 ГБ на диске. При повторном запуске существующий диск прошивки
не перезаписывается.

Последующие запуски: `powershell -ExecutionPolicy Bypass -File qemu\mini2\run_stand_windows.ps1`
Остановка: `powershell -ExecutionPolicy Bypass -File scripts\stop_windows.ps1`

Панель: **http://127.0.0.1:8765/**

## Состав порта (файлы поверх репозитория)

| Файл | Назначение |
|---|---|
| `setup_windows.ps1` | установка зависимостей + runtime + запуск |
| `scripts/install_runtime_windows.py` | распаковка runtime с Windows-фолбэком symlink'ов |
| `scripts/stop_windows.ps1` | остановка стенда |
| `qemu/mini2/guest/init-windows` | гостевой `/init` без 9p (корень уже в initramfs) |
| `qemu/mini2/guest/mini2-windows.start` | гостевой бутстрап: tmpfs-LED + TCP-агент + HTTP-ключи |
| `qemu/mini2/tools/build_boot_windows.py` | сборка initramfs-win.cpio.gz из alpine_root |
| `qemu/mini2/tools/start_windows.py` | запуск QEMU (TCP-консоль, dsound, NAT) |
| `qemu/mini2/tools/host_helper.py` | микрофон (19093) + PEM/время (19094) + hardware.json |
| `qemu/mini2/viewer/server_windows.py` | панель (запуск QEMU через python, без bash) |
| `qemu/mini2/viewer/led_bridge_windows.py` | приём LED-потока с гостя (TCP 19095) |
| `qemu/mini2/run_stand_windows.ps1` | запуск стенда |
| `qemu/mini2/tools/console.py` | заменяет оригинал: unix-сокет → TCP-фолбэк (обратно совместим) |
| `qemu/mini2/tools/hardware_rpc.py` | заменяет оригинал: `sys.executable` вместо `/usr/bin/python3` |

Не тронуты: `keys/`, `assets/`, ext4-диск прошивки, гостевые бинарники
(`mic_relay`, `pem_proxy`, `btvirt`), `viewer/index.html|app.js|style.css`,
`console_tail.py`, `status.sh`, `alice-start.sh`.

## Что работает

- Прошивка Mini 2 запускается в QEMU (`platformd`, `mediad`, `telemetry`).
- Звук Алисы — через dsound/wasapi.
- LED-кольцо и часы — через TCP-мост в панель.
- Микрофон — PCM 48 кГц с хоста в гостевую ALSA (тот же транспорт, что на macOS).
- PEM-адаптер keymaster (`export`/`sign`/`decrypt`).
- NAT-сеть, SSH `127.0.0.1:2222`.
- Панель: консоль, статусы служб, запуск/стоп/перезагрузка.

## Ограничения (как и в macOS-версии)

- **Привязка аккаунта не подтверждена.** Голосовое приветствие, поток
  микрофона и работа PEM не доказывают успешный onboarding.
- **BLE-мост для приложения Яндекса**: приложение не обнаруживает колонку
  даже на macOS (публичный API CoreBluetooth не позволяет воспроизвести
  ManufacturerData `0x0905`/`04 4b`). Windows-версия BLE не портирована
  (WinRT `GattServiceProvider` теоретически умеет manufacturer data, но это
  не проверено — не объявляйте рабочим без теста приложением).
- **Wi-Fi-радио нет**: только NAT (wired shim). LAN-мост `enable_lan.sh`
  (vmnet) на Windows не портирован — при желании можно поднять tap-адаптер.
- QEMU работает через TCG (программная эмуляция) — загрузка прошивки
  медленнее, чем HVF на M-чипах. На x64 это нормально; на Windows ARM64
  QEMU x64-сборка пойдёт через эмуляцию — возможна значительная потеря скорости.

## Диагностика

```powershell
curl http://127.0.0.1:8765/api/firmware          # статус прошивки
curl http://127.0.0.1:8765/api/hardware          # микрофон/мост
python qemu\mini2\tools\console.py 'ps | grep maind'
Get-Content qemu\mini2\run\console.log -Tail 40
Get-Content qemu\mini2\run\host-helper.log -Tail 20
Get-Content qemu\mini2\run\led_bridge.log -Tail 20
```

Порты (все только на 127.0.0.1): 8765 панель, 19093 микрофон, 19094
PEM/время, 19095 LED, 19096 сериальная консоль, 2222 SSH, 8443 HTTPS гостя.

## Проверено/не проверено

Проверено сквозно (Linux-хост, тот же кроссплатформенный Python-код + QEMU
9.0.2 aarch64 TCG, реальный runtime из репозитория):

- сборка initramfs (5784 записи, 335 symlink'ов, exec-биты сохранены);
- загрузка прошивки без 9p: initramfs → Alpine → `/dev/vda` (для этого
  `init-windows` явно подгружает `virtio_pci` — busybox modprobe без udev
  не резолвит PCI-алиасы, без этого диски не появляются);
- сервисы прошивки: `platformd`, `mediad`, `telemetry`, `bluetoothd`,
  `sound` — все зелёные в `/api/firmware` (fresh=true);
- PEM-ключи: гость забирает их с хост-хелпера по HTTP 10.0.2.2:19094
  (после настройки сети), `pem_proxy` стартует;
- микрофон: гостевой `mic_relay` подключён к хостовому TCP 19093;
- LED: живое кольцо реальной прошивки идёт в панель (состояния
  listen/speak/think, реальные цвета), статус firmware обновляется каждые 5 с;
- панель, SSE-события, консоль по TCP, `console.py`.

Не проверено (нет Windows-машины в рамках порта): захват микрофона
sounddevice/WASAPI, dsound/wasapi-бэкенды QEMU, BLE-мост (winsdk),
winget-установка, PowerShell-скрипты. Эти места изолированы и падают
безопасно, не ломая остальной стенд.

Важные уроки при переносе:

- `virtio_pci` обязателен в init (см. выше);
- в busybox ash подшелл умирает целиком при неудачном redirect — в
  LED-агенте нельзя использовать `read <файл` без проверки существования
  (используется `$(cat ...)`);
- файл статуса прошивки появляется не сразу — агент должен переживать его
  отсутствие.
