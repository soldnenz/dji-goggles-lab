# Method 1 — USB gadget

Goggles are the USB host. The computer is a gadget that looks like an
Android accessory, then DUML and H.264 go over bulk.

Two implementations in this repo: Linux `raw_gadget` and a macOS kext.
Same method.

## Enumeration

| Step | What |
| --- | --- |
| 1 | Advertise VID `18d1`. Linux starts as PID `4ee0`, current Mac publish uses `2d00`. Strings: DJI / com.dji.logiclink / … |
| 2 | Host: vendor `0x33` GET_PROTOCOL, `0x34` SEND_STRING, `0x35` START |
| 3 | Re-enumerate as accessory `18d1:2d01` |
| 4 | Bulk OUT = goggles → gadget, bulk IN = gadget → goggles |
| 5 | DUML v1, CRC8 seed `0x77`, CRC16 seed `0x3692`, sender type `0x02` |
| 6 | Identity cmds `0x81` / `0x82` / `0x88`. Video magic `55 CC 4A 57`, then LE32 length, then Annex-B |

If a firmware wants extra “arm” packets, capture them on your own unit.
Do not check in MACs or Wi-Fi BSSIDs.

## Linux (`linux-gadget/`)

Pi 4B. `dtoverlay=dwc2,dr_mode=peripheral`. Feed 5V on GPIO so USB-C stays
data.

```sh
sudo modprobe raw_gadget
sudo env PYTHONPATH=linux-gadget python3 -m pi_endpoint.endpoint \
  --out /tmp/goggles.h264 --log-dir /tmp/goggles-logs -v
```

`gold_app_seq.py` is empty (we stripped unique capture data). Generic
identity replies are in `aoa.py`.

## macOS (`mac-usb/`)

`IOUSBDeviceController` on `usb-drd0` / `usb-drd1`. The kext keeps the
stock NCM description (`05AC:1905`), publishes accessory for a lease,
puts NCM back if userspace dies. `link` opens user client type 123.

Goggles must be host (OTG). `watch` shows which DRD moved.

Kext: [03-macos-kext.md](03-macos-kext.md).

## Not this method

RNDIS cable or the goggles Wi-Fi AP is method 2, and that UDP path is
Goggles 3 only.
