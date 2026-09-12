# Goggles liveview lab

Two ways to pull live video off DJI goggles. The rest of the tree is just
different code for those two ways.

Method 2 (IP) is **Goggles 3 only**. The UDP share-liveview path was taken
off G3 Wi-Fi / RNDIS. Do not expect Integra / G2 / Goggles 2 to speak it.

```
                    goggles
         USB host          USB device / Wi-Fi AP
              |                    |
         METHOD 1              METHOD 2 (G3)
         AOA gadget            share liveview
         bulk 55 CC            UDP :9003
              |                    |
     linux-gadget/              ip-liveview/
     mac-usb/                   wifi / rndis / tetherkit
```

| | Method 1 | Method 2 (Goggles 3 only) |
| --- | --- | --- |
| What the goggles are | USB host (OTG / dongle) | USB device, or Wi-Fi AP |
| What the computer is | USB gadget (Pi or Mac) | UDP client on :9003 |
| Cable | goggles host the port | no OTG; goggles stay a device |
| Video | `55 CC 4A 57` + Annex-B | type-2 UDP, H.264 at +0x14 |
| USB IDs | gadget `18d1:2d01` | goggles `2CA3:0020` |

OTG on the goggles = method 1. OTG off + Share Live View (Wi-Fi or USB) = method 2.

## Method 1 — USB gadget

Goggles enumerate you as an Android accessory, then dump H.264 on bulk.
Same USB story on Linux and on a Mac; only the gadget API changes.

Linux (`linux-gadget/`), Pi 4B, `dwc2` peripheral:

```sh
# /boot/firmware/config.txt : dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint --out /tmp/goggles.h264 -v
```

macOS (`mac-usb/`), Apple Silicon DRD (`usb-drd0` / `usb-drd1`):

```sh
cd mac-usb
make userspace kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```

Kext load is the usual 1TR / Allow / AuxKC mess. Notes: [docs/03-macos-kext.md](docs/03-macos-kext.md).
USB/DUML: [docs/01-usb-gadget.md](docs/01-usb-gadget.md).

Phone-app captures with MACs and session blobs are not in this repo.
`linux-gadget/pi_endpoint/gold_app_seq.py` is empty.

## Method 2 — IP liveview (Goggles 3)

Goggles 3 can share live view without you pretending to be a phone.

On the goggles: **Share Live View to a Mobile Device via Wi-Fi**, or plug
USB with OTG off (they show up as Remote NDIS).

| How you join | Goggles address | Your address |
| --- | --- | --- |
| Wi-Fi AP | `192.168.2.1:9003` | DHCP from the goggles SSID |
| USB on Windows | `192.168.60.2:9003` | `192.168.60.1/24`, empty gateway |
| USB on macOS | same | `tetherkit-cli` brings up `feth0`, then the same /24 |

UDP is the same in all three cases (`ip-liveview/protocol.py`):

| Type | Size / notes |
| --- | --- |
| 0 handshake | 48 bytes. Byte 7 = XOR of bytes 0..6. Session in the header. |
| 2 video | Annex-B starts at offset `0x14`. Seq += 8. |
| 4 ACK | Required. Optional RTX list; first missing seq must be first. |
| 1 data | Telemetry ~10 Hz after handshake. |

Bitrate hint is extra: USB interface 4 (`2CA3:0020` MI04), DUML `0x51/0x29`.
Do not `set_configuration` or you kill RNDIS.

Stream is High Profile and almost never has an IDR. `ffplay -f h264` and
VideoToolbox will sit there. `liveview.py` decodes with libavcodec
`FLAG2_SHOW_ALL` and blits raw YUV.

```sh
python3 -m pip install -r ip-liveview/requirements.txt
python3 ip-liveview/liveview.py --wifi
python3 ip-liveview/mac_wired.py --view
```

More: [docs/02-ip-liveview.md](docs/02-ip-liveview.md).

Windows client reverse (SquirrelReceiver.exe): branch `exe-reverse`,
plain text `docs/squirrel_exe_reverse.txt`.

## Layout

| Path | Method | What |
| --- | --- | --- |
| `linux-gadget/` | 1 | Pi `raw_gadget` |
| `mac-usb/` | 1 | macOS kext + userspace |
| `ip-liveview/` | 2 (G3) | UDP receiver, Mac RNDIS, viewer |
| `docs/` | | longer notes |

```sh
python3 -m unittest discover -s ip-liveview/tests
PYTHONPATH=linux-gadget python3 -m unittest discover -s linux-gadget/tests
```
