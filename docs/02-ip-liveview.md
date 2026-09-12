# Method 2 — IP liveview (Goggles 3 only)

Goggles 3 share live view as UDP port 9003. This is not the AOA gadget
path, and it was not tested on Goggles 2 / Integra.

On the unit: **Share Live View to a Mobile Device via Wi-Fi**, or USB with
OTG **off**.

| Join | L2 | You | Goggles |
| --- | --- | --- | --- |
| Wi-Fi | goggles AP | DHCP | `192.168.2.1:9003` |
| Windows USB | Remote NDIS | `192.168.60.1/24`, no gateway | `192.168.60.2:9003` |
| macOS USB | `tetherkit-cli` → `feth0` | same /24 | same peer |

`protocol.py`, `receiver.py`, `liveview.py` are shared. `mac_wired.py` only
creates the NIC.

## UDP header (8 bytes)

Little-endian. Bit 15 of length is always set (`0x8000`).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | u16 | length \| 0x8000 |
| 2 | u16 | session |
| 4 | u16 | seq |
| 6 | u8 | type |
| 7 | u8 | XOR of bytes 0..6 |

| Type | Meaning |
| --- | --- |
| 0 | handshake, 48 bytes, fixed tail |
| 1 | data / window / DUML ~10 Hz |
| 2 | video; H.264 at +0x14; seq step 8 |
| 3 | file (seen, unused here) |
| 4 | ACK from the client (required) |
| 5 | command |
| 6 | extra ACK |

Type-4 resend list: missing type-2 seqs, step 8, **first hole first** or
the goggles drop the whole list.

MI04 (`2CA3:0020` if 4, class `ff/43/01`): optional bitrate DUML
cmdset `0x51` cmd `0x29`, sender `0x1B`, 22500 kbps / 250 ms. Claim the
interface. Do not reset the device.

## Decoder

High Profile, almost no IDR. VideoToolbox waits forever. `ffplay -f h264`
on a pipe buffers then dies after one lost AU. `liveview.py` uses
`FLAG2_SHOW_ALL` + `LOW_DELAY` and feeds ffplay raw YUV.
