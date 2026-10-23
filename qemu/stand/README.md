# Стенд с двумя моделями: Мини 2 и Миди (Windows)

Общий Windows-слой поверх [`qemu/mini2`](../mini2): один лаунчер QEMU и одна панель,
в которой модель выбирается на ходу — **Мини 2** (ARM32) или **Миди** (ARM64).
9p не используется: Alpine-bootstrap упакован в self-contained initramfs, как и в
[`README-WINDOWS.md`](../../README-WINDOWS.md).

## Запуск

```powershell
# панель + QEMU выбранной модели
powershell -ExecutionPolicy Bypass -File qemu\stand\run_stand_windows.ps1 -Model midi

# или напрямую
python qemu\stand\tools\start_windows.py --model mini
python qemu\stand\viewer\server_windows.py        # панель: http://127.0.0.1:8765/
```

Модель переключается в шапке панели; `boot/stop/reboot` — там же. Консоль гостя —
TCP `127.0.0.1:19096`, LED Мини 2 — TCP `127.0.0.1:19095`.

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

## Файлы

| Путь | Назначение |
|---|---|
| `run_stand_windows.ps1` | запуск панели и QEMU выбранной модели |
| `tools/start_windows.py` | CLI `--model mini\|midi` |
| `tools/build_boot_windows.py` | сборка initramfs из `alpine_root` |
| `tools/console.py` | команда в гостевую консоль (TCP 19096) |
| `tools/stand/` | модели, cpio, QEMU-контроллер, LED-мост |
| `viewer/server_windows.py` | панель и HTTP API |
| `viewer/index.html`, `app.js` | интерфейс: сцена Мини 2 / Миди, сервисы, консоль |
| `viewer/style.css` | не копируется: отдаётся из `qemu/mini2/viewer/style.css` |
| `viewer/style-extra.css` | переключатель моделей и сцена Миди |
| `guest/` | `init-windows`, `mini2-windows.start`, `midi-windows.start` |

## Ограничения

- TCG: загрузка ~30–60 с, QEMU ~150 % одного ядра.
- Микрофон, BLE для приложения и `keymaster` не портированы (как в `qemu/mini2`).
- У Миди нет эмуляции I2C-LED — кольцо в панели анимируется независимо от прошивки.
- `data/`, `run/` исключены из git.
