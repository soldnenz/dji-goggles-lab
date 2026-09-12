# Method 1 — USB gadget

One method: the goggles are USB **host**, the computer is a USB **device**
that looks like an Android accessory, then DUML + `55 CC` video on bulk.

Two implementations of that method live in this repository.

## Shared USB / DUML behaviour

1. Advertise Google VID `18d1`, first as `4ee0` (Linux) or `2d00` (current
   Mac publish), strings in the AOA table (`DJI`, `com.dji.logiclink`, …).
2. Host sends vendor requests `0x33` GET_PROTOCOL, `0x34` SEND_STRING,
   `0x35` START.
3. Re-enumerate as accessory `18d1:2d01`.
4. Bulk OUT (goggles → gadget) and bulk IN (gadget → goggles).
5. DUML v1, CRC8 seed `0x77`, CRC16 seed `0x3692`, sender type `0x02`.
6. Identity `cmd 0x81/0x82/0x88`. Video magic `55 CC 4A 57` (`0x574A`) plus
   little-endian length plus Annex-B.

If a firmware wants extra arm packets, capture them on **your** device. Do
not commit captures that contain MACs, Wi‑Fi BSSIDs, or session blobs.

## Linux implementation (`linux-gadget/`)

Pi 4B, `dtoverlay=dwc2,dr_mode=peripheral`, `modprobe raw_gadget`.
Power the Pi from GPIO 5V so USB-C stays data. Endpoint:

```sh
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint \
  --out /tmp/goggles.h264 --log-dir /tmp/goggles-logs -v
```

`gold_app_seq.py` is empty on purpose (redacted unique capture). Generic
identity replies remain in `aoa.py`.

## macOS implementation (`mac-usb/`)

Apple Silicon DRD ports expose `IOUSBDeviceController`. The kext snapshots
stock NCM (`05AC:1905`), publishes accessory `DeviceDescription` with a
lease, restores on timeout. `link` opens user client type 123 and speaks
the same `55 CC` framing.

Goggles must be in **host** role (OTG / dongle). Wrong port → wrong `usb-drd*`;
use `watch`.

Kext loading: [03-macos-kext.md](03-macos-kext.md).

## Not this method

Windows/macOS talking to goggles RNDIS, or joining the goggles Wi‑Fi AP, is
**Method 2**. The Mac is then the USB host (or just a Wi‑Fi client).
