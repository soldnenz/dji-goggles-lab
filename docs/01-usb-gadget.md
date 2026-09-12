# USB gadget

Очки — USB host. Комп — gadget (Android accessory). Дальше DUML и H.264
на bulk. `linux-gadget/` и `mac-usb/` делают одно и то же, разными API.

## Enumeration

VID `18d1`. На Linux gadget сначала бывает PID `4ee0`, на текущем Mac
publish — `2d00`. Строки в дескрипторе: DJI / com.dji.logiclink / …

Хост шлёт vendor `0x33` GET_PROTOCOL, `0x34` SEND_STRING, `0x35` START,
перечисление accessory `18d1:2d01`. Bulk OUT — очки→gadget, IN — обратно.

DUML v1, CRC8 seed `0x77`, CRC16 `0x3692`, sender type `0x02`. Identity
`0x81` / `0x82` / `0x88`. Видео: `55 CC 4A 57`, LE32 длина, Annex-B.

Если прошивка ждёт ещё arm-пакеты — снимай со своих очков. Чужие
MAC/BSSID в git не нужны.

## Linux

Pi 4B, `dtoverlay=dwc2,dr_mode=peripheral`. Питай 5V на GPIO: иначе
USB-C начинает брать VBUS с очков и роли едут.

```sh
sudo modprobe raw_gadget
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint \
  --out /tmp/goggles.h264 --log-dir /tmp/goggles-logs -v
```

`gold_app_seq.py` пустой. Identity без серийников — `aoa.py`.

## macOS

`IOUSBDeviceController` на `usb-drd0` / `usb-drd1`. Kext держит стоковый
NCM (`05AC:1905`), на lease публикует accessory и откатывает, если
userspace умер. `link` открывает user client type 123.

Очки должны быть host (OTG). Не тот Type-C — не тот drd; смотри `watch`.

Kext: [03-macos-kext.md](03-macos-kext.md).

RNDIS / Wi-Fi AP очков — это метод 2, и он только для Goggles 3.
