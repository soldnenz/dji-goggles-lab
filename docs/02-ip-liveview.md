# Method 2 — IP liveview

One method: the goggles share liveview as UDP `:9003`.

Three ways onto that network:

| Implementation | L2 | Bind |
|---|---|---|
| Wi‑Fi | goggles AP | DHCP, peer `192.168.2.1` |
| Windows USB | Remote NDIS | `192.168.60.1/24`, peer `.2` |
| macOS USB | userspace RNDIS (`tetherkit-cli`, `feth0`) | same as Windows |

The UDP grammar does not change. `protocol.py` / `receiver.py` / `liveview.py`
are shared. `mac_wired.py` only creates the NIC.

OTG **off**. OTG on is Method 1.

Handshake, ACK, RTX, MI04, decoder notes: see the previous IP write-up below
and `ip-liveview/`.

## UDP

- 8-byte header, flag `0x8000`, byte 7 = XOR of 0..6.
- Type 0 handshake 48 bytes; session in header; tail is a fixed template.
- Type 2 video; Annex-B at `0x14`; seq += 8.
- Type 4 ACK required. RTX list optional; first missing seq must be first
  in the list or the goggles ignore it.
- MI04 (`2CA3:0020` if 4) optional bitrate DUML `0x51/0x29`. Do not
  `set_configuration` (RNDIS would drop).

## Decoder

High Profile, rare IDR. VideoToolbox and piped `ffplay -f h264` fail.
`liveview.py`: libavcodec `FLAG2_SHOW_ALL` + raw YUV into ffplay.
