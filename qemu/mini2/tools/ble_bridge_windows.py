#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BLE-мост для Windows — экспериментальный аналог HardwareBridge.swift (CoreBluetooth).

Эмулирует BLE-периферию Яндекс Станции Мини 2 средствами WinRT (winsdk):

  - реклама через BluetoothLEAdvertisementPublisher: локальное имя
    'Yandex Station Mini 2 NK8K', сервис 664578b6-c390-42d8-956e-c1ae8b646436,
    ManufacturerData company 0x0905 с байтами 04 4b
    (то, чего не умел CoreBluetooth — WinRT умеет);
  - GATT-сервер через GattServiceProvider: 6 характеристик;
  - все read/write/notify операции проксируются через HTTP POST на локальный
    hardware_rpc.py (127.0.0.1:19092) — формат в точности как в HardwareBridge.swift:
      запрос  {'action': 'read'|'write'|'subscribe'|'unsubscribe', 'index': 0..5,
               'data': base64, 'offset': int}
      ответ  {'ok': bool, 'data': base64}
  - статус пишется в stdout и в файл run/hardware.json (ключ 'bluetooth').

Запуск возможен только на Windows. Зависимости: stdlib + winsdk.
"""

import asyncio
import base64
import json
import sys
import time
import urllib.request
from uuid import UUID

# --- Проверка платформы: работаем только на Windows ---------------------------
if sys.platform != "win32":
    print("Эта утилита предназначена только для Windows (нужен WinRT BLE и winsdk).")
    print("На macOS используйте HardwareBridge.swift, на Linux — bluez-аналог.")
    sys.exit(1)

from winsdk.windows.devices.bluetooth import BluetoothLEManufacturerData
from winsdk.windows.devices.bluetooth.advertisement import (
    BluetoothLEAdvertisement,
    BluetoothLEAdvertisementPublisher,
    BluetoothLEAdvertisementPublisherStatus,
)
from winsdk.windows.devices.bluetooth.genericattributeprofile import (
    GattLocalCharacteristicParameters,
    GattServiceProvider,
)
from winsdk.windows.storage.streams import DataReader, DataWriter

# --- Константы, зеркалирующие HardwareBridge.swift ----------------------------

SERVICE_UUID = "664578b6-c390-42d8-956e-c1ae8b646436"
LOCAL_NAME = "Yandex Station Mini 2 NK8K"
MANUFACTURER_COMPANY_ID = 0x0905  # company id в ManufacturerData рекламы
MANUFACTURER_PAYLOAD = b"\x04\x4b"  # байты 04 4b

CHARACTERISTIC_UUIDS = [
    "f25d4a0d-6266-4254-943e-3e20606f2fa6",  # 0: write
    "4276d829-46ce-4ce9-9f30-30dbb9a43724",  # 1: read
    "29d49103-16f4-4fcd-85c7-42d0e43d16d9",  # 2: write
    "9879f69f-510f-4a0c-b500-79de90342997",  # 3: read + notify (статус станции)
    "5b66e7df-1b0f-4a9d-8492-5c3f3b866c80",  # 4: write
    "e985aa00-e701-4d5d-96b9-f38ae3d7ee16",  # 5: read
]
# свойства характеристик: [write, read, write, read+notify, write, read]
CHARACTERISTIC_PROPERTIES = [
    {"write": True},
    {"read": True},
    {"write": True},
    {"read": True, "notify": True},
    {"write": True},
    {"read": True},
]
NOTIFY_INDEX = 3  # индекс notify-характеристики (статус станции)

RPC_URL = "http://127.0.0.1:19092/"
RPC_TIMEOUT = 12  # как timeoutInterval=12 в HardwareBridge.swift

STATUS_PATH_SUFFIX = "run/hardware.json"


# --- Утилиты WinRT: bytes <-> IBuffer ----------------------------------------

def bytes_to_buffer(data: bytes):
    """bytes -> winrt IBuffer (через DataWriter)."""
    writer = DataWriter()
    if data:
        writer.write_bytes(list(data))
    return writer.detach_buffer()


def buffer_to_bytes(buf) -> bytes:
    """winrt IBuffer -> bytes (через DataReader)."""
    if buf is None or buf.length == 0:
        return b""
    reader = DataReader.from_buffer(buf)
    return bytes(reader.read_bytes(buf.length))


# --- HTTP-прокси к локальному hardware_rpc.py ---------------------------------

def rpc_sync(action: str, index: int, data: bytes = b"", offset: int = 0):
    """Синхронный POST к hardware_rpc.py; возвращает (ok, data|None)."""
    body = json.dumps({
        "action": action,
        "index": index,
        "data": base64.b64encode(data).decode("ascii"),
        "offset": offset,
    }).encode("utf-8")
    req = urllib.request.Request(
        RPC_URL, data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=RPC_TIMEOUT) as resp:
            obj = json.loads(resp.read().decode("utf-8"))
        if obj.get("ok") is True and "data" in obj:
            return True, base64.b64decode(obj["data"])
        return False, None
    except Exception:
        return False, None


async def rpc(action: str, index: int, data: bytes = b"", offset: int = 0):
    """Асинхронная обёртка rpc_sync (urllib уходит в отдельный поток)."""
    return await asyncio.to_thread(rpc_sync, action, index, data, offset)


# --- Мост: реклама + GATT-сервер ----------------------------------------------

class Bridge:
    def __init__(self, root: str):
        self.root = root.rstrip("\\/")
        self.chars = {}          # index -> GattLocalCharacteristic
        self.last_status = b""   # последний разосланный статус (дедупликация)
        self.subscribed = False  # есть ли подписчики на notify
        self.status = "starting"
        self.publisher = None
        self.provider = None
        self.loop = asyncio.get_running_loop()

    # --- Статус: stdout + run/hardware.json (ключ 'bluetooth') ----------------

    def save(self):
        """Обновить ключ 'bluetooth' в run/hardware.json, сохранив прочие ключи."""
        path = f"{self.root}/{STATUS_PATH_SUFFIX}"
        state = {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, ValueError):
            pass
        state["bluetooth"] = self.status
        state["timestamp"] = time.time()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, sort_keys=True)
        except OSError as e:
            print(f"[ble] не удалось записать {path}: {e}", flush=True)

    def set_status(self, status: str):
        self.status = status
        print(f"[ble] bluetooth: {status}", flush=True)
        self.save()

    # --- Запуск ----------------------------------------------------------------

    async def start(self):
        self.set_status("starting")
        await self.start_gatt_server()
        await self.start_advertising()
        # Периодический опрос статуса (аналог Timer 1с в HardwareBridge.swift):
        # читаем характеристику 3 через hardware_rpc и рассылаем notify.
        while True:
            await asyncio.sleep(1)
            if not self.subscribed:
                continue
            ok, data = await rpc("read", NOTIFY_INDEX)
            if not ok or data is None or data == self.last_status:
                continue
            await self.notify_status(data)

    # --- GATT-сервер ------------------------------------------------------------

    async def start_gatt_server(self):
        """Создать GATT-сервис и 6 характеристик, повесить обработчики."""
        result = await GattServiceProvider.create_async(UUID(SERVICE_UUID))
        self.provider = result.service_provider
        if self.provider is None:
            self.set_status(f"gatt_error: {result.error}")
            raise RuntimeError(f"не удалось создать GATT-сервис: {result.error}")

        for index, uuid in enumerate(CHARACTERISTIC_UUIDS):
            params = GattLocalCharacteristicParameters()
            props = CHARACTERISTIC_PROPERTIES[index]
            if props.get("read"):
                params.read = True
            if props.get("write"):
                params.write = True
            if props.get("notify"):
                params.notify = True
            res = await self.provider.service.create_characteristic_async(UUID(uuid), params)
            if res.characteristic is None:
                self.set_status(f"gatt_error char {index}: {res.error}")
                raise RuntimeError(f"не удалось создать характеристику {index}: {res.error}")
            ch = res.characteristic
            self.chars[index] = ch

            # Обработчики — аналоги didReceiveRead / didReceiveWrite / didSubscribe
            ch.add_read_requested(self._on_read_requested)
            ch.add_write_requested(self._on_write_requested)
            if props.get("notify"):
                ch.add_subscribed_clients_changed(self._on_subscribed_changed)

        print(f"[ble] GATT-сервис {SERVICE_UUID}: {len(self.chars)} характеристик", flush=True)

    def _index_of(self, characteristic) -> int | None:
        """Найти индекс характеристики по её UUID."""
        try:
            u = str(characteristic.uuid).lower()
        except Exception:
            return None
        for i, cu in enumerate(CHARACTERISTIC_UUIDS):
            if cu == u:
                return i
        return None

    def _schedule(self, coro):
        """Запустить корутину на главном event loop (события WinRT приходят из
        других потоков, поэтому нужен run_coroutine_threadsafe)."""
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    # --- Обработка read-запросов (аналог didReceiveRead) ------------------------

    def _on_read_requested(self, sender, args):
        """Чтение характеристики: проксируем в hardware_rpc, поддерживаем offset."""
        index = self._index_of(sender)
        if index is None:
            return
        deferral = args.get_deferral()
        request = args.request

        async def run():
            try:
                ok, data = await rpc("read", index)
                if not ok or data is None:
                    # аналог .unlikelyError в Swift: отдаём пустое значение
                    request.respond(bytes_to_buffer(b""))
                    return
                offset = request.offset
                if offset > len(data):
                    # аналог .invalidOffset в Swift
                    request.respond(bytes_to_buffer(b""))
                    return
                request.respond(bytes_to_buffer(data[offset:]))
            except Exception as e:
                print(f"[ble] read[{index}] не удался: {e}", flush=True)
                try:
                    request.respond(bytes_to_buffer(b""))
                except Exception:
                    pass
            finally:
                deferral.complete()

        self._schedule(run())

    # --- Обработка write-запросов (аналог didReceiveWrite) ----------------------

    def _on_write_requested(self, sender, args):
        """Запись в характеристику: склеиваем пакеты по offset и шлём в hardware_rpc."""
        index = self._index_of(sender)
        if index is None:
            return
        deferral = args.get_deferral()
        requests = list(args.requests)
        if not requests:
            deferral.complete()
            return

        async def run():
            try:
                # сортируем по offset и склеиваем (как в HardwareBridge.swift)
                requests.sort(key=lambda r: r.offset)
                data = b"".join(buffer_to_bytes(r.value) for r in requests)
                ok, _ = await rpc("write", index, data, requests[0].offset)
                for r in requests:
                    try:
                        if ok:
                            r.respond()  # успех
                        else:
                            r.respond_with_protocol_error(0x0E)  # unlikely error
                    except Exception:
                        # respond может быть недоступен для write-without-response
                        pass
            except Exception as e:
                print(f"[ble] write[{index}] не удался: {e}", flush=True)
            finally:
                deferral.complete()

        self._schedule(run())

    # --- Подписки на notify (аналог didSubscribeTo/didUnsubscribeFrom) ----------

    def _on_subscribed_changed(self, sender, args):
        """Кто-то подписался/отписался от notify-характеристики."""
        was = self.subscribed
        try:
            self.subscribed = len(sender.subscribed_clients) > 0
        except Exception:
            return
        if self.subscribed and not was:
            print("[ble] центральное устройство подписалось на notify", flush=True)
            # аналог rpc("subscribe",3) в Swift
            self._schedule(rpc("subscribe", NOTIFY_INDEX))
        elif not self.subscribed and was:
            print("[ble] подписка на notify снята", flush=True)
            # аналог rpc("unsubscribe",3) в Swift
            self._schedule(rpc("unsubscribe", NOTIFY_INDEX))

    async def notify_status(self, data: bytes):
        """Разослать статус подписанным клиентам (аналог updateValue)."""
        ch = self.chars.get(NOTIFY_INDEX)
        if ch is None:
            return
        try:
            buf = bytes_to_buffer(data)
            try:
                # новый API (Windows 10 1903+)
                await ch.notify_value_async(buf)
            except AttributeError:
                # старый синхронный API
                ch.notify_value(buf)
            self.last_status = data
        except Exception as e:
            print(f"[ble] notify не удался: {e}", flush=True)

    # --- Реклама (BluetoothLEAdvertisementPublisher) ------------------------------

    async def start_advertising(self):
        """Запустить BLE-рекламу: имя, сервис, ManufacturerData 0x0905 = 04 4b."""
        adv = BluetoothLEAdvertisement()
        adv.local_name = LOCAL_NAME
        adv.service_uuids.append(UUID(SERVICE_UUID))  # сервис в рекламе

        # ManufacturerData — то, чего не умел CoreBluetooth: company 0x0905, байты 04 4b
        md = BluetoothLEManufacturerData()
        md.company_id = MANUFACTURER_COMPANY_ID
        md.data = bytes_to_buffer(MANUFACTURER_PAYLOAD)
        adv.manufacturer_data.append(md)

        self.publisher = BluetoothLEAdvertisementPublisher(adv)
        self.publisher.add_status_changed(self._on_publisher_status)
        await self.publisher.start_async()
        self.set_status("advertising")

    def _on_publisher_status(self, sender, args):
        """Статус рекламщика — пишем в run/hardware.json (ключ 'bluetooth')."""
        try:
            name = BluetoothLEAdvertisementPublisherStatus(args.status).name
        except Exception:
            name = str(args.status)
        if args.error is not None:
            self.set_status(f"publisher error: {args.error}")
        else:
            self.set_status(f"publisher: {name.lower()}")


async def main():
    # Корень run/ — первый аргумент или текущий каталог (как в HardwareBridge.swift)
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    bridge = Bridge(root)
    print(f"[ble] Windows BLE-мост запускается (root={root})", flush=True)
    try:
        await bridge.start()
    except Exception as e:
        bridge.set_status(f"error: {e}")
        print(f"[ble] фатальная ошибка: {e}", flush=True)
        raise


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[ble] остановлено", flush=True)
