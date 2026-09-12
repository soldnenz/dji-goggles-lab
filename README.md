# Goggles liveview lab

Independent notes and code for receiving DJI Goggles 3 liveview.
Not affiliated with DJI. Not a product. Not a license client.

There are **two methods**. Everything else is an implementation of one of them.

```
                         DJI Goggles 3
                    USB host │ USB device / Wi-Fi AP
                             │
         Method 1            │            Method 2
    gadget / AOA bulk        │       share liveview IP
    55 CC + DUML + H.264     │       UDP :9003 type-2
                             │
     implementations         │         implementations
     • Linux raw_gadget (Pi) │         • Wi-Fi AP 192.168.2.1
     • macOS IOUSBDevice     │         • USB RNDIS on Windows
       kext + userspace      │         • USB RNDIS on macOS
                             │           (tetherkit-cli / feth0)
```

| | Method 1 — USB gadget | Method 2 — IP liveview |
|---|---|---|
| USB host | Goggles | Mac/PC (or nobody on Wi‑Fi) |
| USB device | Pi or Mac | Goggles `2CA3:0020` |
| On the wire | bulk `55 CC` + DUML | UDP header + XOR-7 |
| Video | channel `0x574A` Annex-B | type-2, H.264 at offset `0x14` |
| Cable role on goggles | host / OTG / dongle | **not** OTG; goggles stay a device |

Do not mix the roles on one cable. OTG on → Method 1. OTG off + RNDIS or Wi‑Fi → Method 2.

---

## Method 1 — USB gadget (one topology, two implementations)

The goggles act as USB **host** and expect an Android Open Accessory-style
device (`18d1:4ee0` then accessory `18d1:2d01`): `GET_PROTOCOL` / `SEND_STRING`
/ `START`, bulk OUT/IN, DUML identity (`0x81`/`0x82`/`0x88`), video framed as
`55 CC 4A 57` + little-endian length + Annex-B.

### Implementation: Linux `raw_gadget` (`linux-gadget/`)

Raspberry Pi 4B, `dwc2` peripheral, Python endpoint. This is the complete
gadget state machine.

```sh
# Pi: dtoverlay=dwc2,dr_mode=peripheral
sudo modprobe raw_gadget
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint \
  --out /tmp/goggles.h264 -v
```

Capture-derived phone-app arm sequences and unique hardware IDs are **not**
in this tree (`APP_SEQ` / `SUSTAIN_SEQ` are empty). Identity replies that are
protocol-generic stay in `aoa.py`.

### Implementation: Apple Silicon kext (`mac-usb/`)

macOS has no public gadget API. `IOUSBDeviceController` on `usb-drd0` /
`usb-drd1` can still present a device. A small kext applies a leased
`DeviceDescription`; userspace opens `IOUSBDeviceInterface` and speaks the
same DUML framing.

```sh
cd mac-usb && make userspace && make kext
./scripts/stage.sh
sudo ./link --controller usb-drd0
./scripts/unstage.sh
```

Third-party kext load: Recovery reduced security, Privacy & Security Allow,
often AuxKC reboot. Lab Mac only. See [docs/03-macos-kext.md](docs/03-macos-kext.md).

Same method as the Pi. Different OS plumbing.

Details: [docs/01-usb-gadget.md](docs/01-usb-gadget.md).

---

## Method 2 — IP liveview (one protocol, three ways onto the LAN)

The goggles already export liveview as UDP `:9003`. No accessory impersonation.

1. Handshake type-0 (48 bytes; byte 7 = XOR of bytes 0..6).
2. Video type-2; ACK type-4 is mandatory; optional RTX list (must start at
   the first hole).
3. Optional bitrate hint on USB **MI04** while RNDIS owns interfaces 0–1.

| Implementation | How you get a NIC | Peer |
|---|---|---|
| Wi‑Fi | join goggles AP | `192.168.2.1:9003` |
| Windows USB | in-box Remote NDIS | `192.168.60.2:9003`, local `192.168.60.1/24` |
| macOS USB | `tetherkit-cli` → `feth0` | same as Windows |

```sh
python3 -m pip install -r ip-liveview/requirements.txt
python3 ip-liveview/liveview.py --wifi
python3 ip-liveview/mac_wired.py --view
```

High Profile / almost no IDR: decode with libavcodec `FLAG2_SHOW_ALL`, not
VideoToolbox and not `ffplay -f h264` on a pipe.

Details: [docs/02-ip-liveview.md](docs/02-ip-liveview.md).

---

## Layout

```
linux-gadget/     Method 1 implementation (Linux Pi)
mac-usb/          Method 1 implementation (macOS kext)
ip-liveview/      Method 2 implementations (Wi-Fi, Mac RNDIS, viewer)
docs/
```

## Tests

```sh
python3 -m unittest discover -s ip-liveview/tests
PYTHONPATH=linux-gadget python3 -m unittest discover -s linux-gadget/tests
```
