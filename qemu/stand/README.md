# Стенд с двумя моделями: Мини 2 и Миди (Windows)

Общий Windows-слой поверх [`qemu/mini2`](../mini2): один лаунчер QEMU и одна панель,
в которой модель выбирается на ходу — **Мини 2** (ARM32) или **Миди** (ARM64).
9p не используется: Alpine-bootstrap упакован в self-contained initramfs, как и в
[`README-WINDOWS.md`](../../README-WINDOWS.md).

## Установка данных

```powershell
python qemu\stand\tools\install_data_windows.py --model all
```

- **mini** — `mini2-backup.ext4`, ядро и `initramfs-win.cpio.gz` из runtime
  (при необходимости вызывает `scripts/install_runtime_windows.py`);
- **midi** — `rootfs.ext4` и `data.ext4` из разбитого gzip-архива в `assets/`.
  Части и распакованные образы сверяются (SHA256, ext4-superblock), распаковка
  атомарная: временный файл → проверка → `os.replace`. Прерванная установка
  больше не оставляет «половину» `rootfs.ext4`, которую потом нельзя отличить
  от готового диска.

Повторный запуск безопасен: корректные образы не трогаются, битые — пересобираются.

## Запуск

```powershell
# панель + QEMU выбранной модели
powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model midi

# или напрямую
python qemu\stand\tools\start_windows.py --model mini
python qemu\stand\viewer\server_windows.py        # панель: http://127.0.0.1:8765/
```

Перед запуском лаунчер делает preflight: проверяет образы, initramfs и QEMU.
Если чего-то нет, панель не стартует, а в консоль выводятся отсутствующие файлы
и готовая команда установки (то же умеет `start_windows.py --model … --check`).
Ту же проверку делает API панели: `boot` без данных возвращает ошибку с подсказкой,
а не «успех» с молча упавшим QEMU.

Модель переключается в шапке панели; `boot/stop/reboot` — там же.

## Порты (только loopback)

| Порт | Назначение |
|---|---|
| `2222` | SSH Мини 2: `hostfwd` → гость `:22` |
| `8443` | HTTPS Мини 2: `hostfwd` → гость `:443` |
| `19093` | микрофонный PCM (host helper, Мини 2) |
| `19094` | `/epoch` и PEM-ключи для гостя (host helper, Мини 2) |
| `19095` | LED и статус гостя → панель |
| `19096` | серийная консоль QEMU |

`hostfwd` и host helper включаются только для Мини 2 — это прежнее поведение
`qemu/mini2/start_windows.py`. Контроллер стенда поднимает
[`qemu/mini2/tools/host_helper.py`](../mini2/tools/host_helper.py) перед стартом
QEMU и останавливает его вместе со стендом; если helper не поднялся, запуск
падает с хвостом его лога, а не молча оставляет гостя без PEM и микрофона.

## Данные

`data/` не хранится в git (проприетарная прошивка, ~1,8 ГБ):

- **mini** — `vmlinuz-lts`, `mini2-backup.ext4`, `mtd4_nv.bin` из
  `assets/runtime.tar.gz.part*` (см. `scripts/install_runtime_windows.py`);
- **midi** — `rootfs.ext4` и `data.ext4`, собранные из дампа Миди
  (`rootfs/` → `mke2fs -d`), плюс тот же `vmlinuz-lts`.

Initramfs для каждой модели собирается из своего `alpine_root`
(запускать в WSL/Linux: нужны настоящие симлинки):

```bash
cd qemu/stand/tools
python -m stand.build --model mini --alpine-root ../../mini2/alpine_root
python -m stand.build --model midi --alpine-root <alpine_root Миди> --out ../../stand/data/midi/initramfs-midi.cpio.gz
```

## Что сделано для Миди

| Отличие | Решение |
|---|---|
| SoC SC2 = Cortex-A55 | `-cpu cortex-a55` (на A53 — `Illegal instruction`) |
| В дампе нет `/lib64` | симлинк `lib64/ld-2.30.so → ../lib/ld-2.30.so` |
| битый `ld.so.cache` | `LD_LIBRARY_PATH=/lib:/usr/lib` в `run.sh`/`onboot.sh` |
| deviceId из efuse | подмена `/proc/cmdline` (`androidboot.deviceid=`) |
| 4 канала 96 кГц | `asound.conf` под virtio-snd (2×48 кГц, mics — FIFO, loopback — null) |
| нет LED/BT/TEE | кольцо в панели декоративное; статусы — от гостевого агента |

## Свежесть состояния

Гостевой агент шлёт LED каждые ~0,2 с и статус служб каждые 5 с. Мост хранит
**host-time** получения (не timestamp гостя, который может уплыть) и отдаёт в API
`firmware_fresh`, `firmware_age`, `led_fresh`, `led_age`. TTL: 20 с для статуса,
5 с для LED. После остановки QEMU, зависания гостя или смерти агента панель
показывает «Нет данных / отчёт устарел», а не последнюю удачную картинку.
`stop`/`reboot` сбрасывают мост сразу.

## Файлы

| Путь | Назначение |
|---|---|
| `run_stand_windows.ps1` | preflight, запуск панели и QEMU выбранной модели |
| `tools/start_windows.py` | CLI `--model mini\|midi`, `--check` — только preflight |
| `tools/install_data_windows.py` | установка/починка образов и initramfs |
| `tools/console.py` | команда в гостевую консоль (TCP 19096) |
| `tools/stand/` | модели, cpio, QEMU-контроллер, LED-мост |
| `viewer/server_windows.py` | панель и HTTP API |
| `viewer/index.html`, `app.js` | интерфейс: сцена Мини 2 / Миди, сервисы, консоль |
| `viewer/style.css` | не копируется: отдаётся из `qemu/mini2/viewer/style.css` |
| `viewer/style-extra.css` | переключатель моделей и сцена Миди |
| `guest/` | `init-windows`, `mini2-windows.start`, `midi-windows.start` |

## Ограничения

- TCG: загрузка ~30–60 с, QEMU ~150 % одного ядра.
- Микрофон и PEM-ключи Мини 2 работают через `host_helper.py`; для Миди такого
  моста нет (его гость не запускает `mic_relay`).
- BLE для приложения и `keymaster` не портированы (как в `qemu/mini2`).
- У Миди нет эмуляции I2C-LED — кольцо в панели анимируется независимо от прошивки.
- `data/`, `run/` исключены из git.
