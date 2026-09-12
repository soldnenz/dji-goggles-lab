# Goggles liveview lab

Два метода. Не три. Не «ещё один драйвер». Два.

Метод 2 (IP) я снимал **только с Goggles 3**. На Integra / G2 / Goggles 2
это UDP не обещаю — не проверял и не хочу врать.

```
                    очки
         USB host              USB device / Wi-Fi AP
              |                         |
         METHOD 1                   METHOD 2 (G3)
         AOA gadget                 share liveview
         bulk 55 CC                 UDP :9003
              |                         |
     linux-gadget/                   ip-liveview/
     mac-usb/                        wifi / rndis / tetherkit
```

|  | Method 1 | Method 2 (только Goggles 3) |
| --- | --- | --- |
| очки | USB host (OTG / dongle) | USB device или Wi-Fi AP |
| комп | gadget (Pi или Mac) | UDP-клиент на :9003 |
| кабель | очки хостят порт | OTG выкл, очки остаются device |
| видео | `55 CC 4A 57` + Annex-B | type-2 UDP, H.264 с +0x14 |
| USB ID | gadget `18d1:2d01` | очки `2CA3:0020` |

OTG на очках = метод 1. OTG выкл + Share Live View (Wi-Fi или USB) = метод 2.
Перепутаешь роли — будешь неделю «чинить протокол», а виноват кабель.

## Method 1 — USB gadget

Очки думают, что ты телефон. AOA, потом H.264 на bulk. На Linux и на Mac
это **один** USB-метод, просто API гаджета разный. Я оба поднял.

Linux (`linux-gadget/`), Pi 4B, `dwc2` peripheral:

```sh
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
```

macOS (`mac-usb/`), Apple Silicon, контроллеры `usb-drd0` / `usb-drd1`:

```sh
cd mac-usb
make userspace kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```

Kext — классика 1TR / Allow / AuxKC, Apple как всегда. Писал тут:
[docs/03-macos-kext.md](docs/03-macos-kext.md).
DUML/AOA: [docs/01-usb-gadget.md](docs/01-usb-gadget.md).

Захваты с телефона с MAC/BSSID в репо не клал. `gold_app_seq.py` пустой
специально — это не «недоделка», это чтобы в паблик не утекли серийники.

## Method 2 — IP liveview (Goggles 3)

Вот тут я вообще не притворяюсь телефоном. G3 сами шарят liveview.

На очках: **Share Live View to a Mobile Device via Wi-Fi**, либо USB
без OTG (они прикидываются Remote NDIS).

| как зайти | адрес очков | твой адрес |
| --- | --- | --- |
| Wi-Fi AP | `192.168.2.1:9003` | DHCP с SSID очков |
| USB Windows | `192.168.60.2:9003` | `192.168.60.1/24`, gateway пустой |
| USB macOS | то же | `tetherkit-cli` поднимает `feth0`, тот же /24 |

На Windows RNDIS из коробки. На маке драйвера нет — поэтому tetherkit,
не потому что я так захотел. UDP один и тот же, см. `ip-liveview/protocol.py`.

| Type | что это |
| --- | --- |
| 0 handshake | 48 байт. Байт 7 = XOR байт 0..6. Session в хедере. |
| 1 data | телеметрия ~10 Hz после хендшейка |
| 2 video | Annex-B с `0x14`. Seq += 8 |
| 4 ACK | обязателен. RTX-список: первая дыра обязана быть первой |

Ещё bitrate hint: USB if 4 (`2CA3:0020` MI04), DUML `0x51/0x29`.
`set_configuration` не трогать — убьёшь RNDIS, потом будешь винить очки.

Стрим High Profile, IDR почти нет. `ffplay -f h264` и VideoToolbox тупо
висят. Я это уже прошёл. `liveview.py` жрёт через libav `FLAG2_SHOW_ALL`
и кидает в окно сырой YUV.

```sh
python3 -m pip install -r ip-liveview/requirements.txt
python3 ip-liveview/liveview.py --wifi
python3 ip-liveview/mac_wired.py --view
```

Подробнее: [docs/02-ip-liveview.md](docs/02-ip-liveview.md).

Разбор чужого Windows-клиента (SquirrelReceiver.exe) — обычный txt, без
md-превью: [docs/squirrel_exe_reverse.txt](docs/squirrel_exe_reverse.txt).
Exe в репо нет, копирайта на диск не льём.

## Где что лежит

| папка | метод | |
| --- | --- | --- |
| `linux-gadget/` | 1 | Pi `raw_gadget` |
| `mac-usb/` | 1 | kext + userspace на маке |
| `ip-liveview/` | 2 (G3) | UDP, Mac RNDIS, вьюер |
| `docs/` | | длинные заметки |

`make` в корне собирает userspace/kext мака. Тестов в паблик не клал —
это лаба, не pytest-фестиваль.
