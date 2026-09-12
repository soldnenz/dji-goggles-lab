"""DJI Goggles 3 IP liveview framing.

On-wire UDP service used when the goggles share liveview (Wi-Fi AP or USB
RNDIS): 48-byte type-0 handshake, XOR of the first 7 header bytes, peers
192.168.2.1:9003 (Wi-Fi) and 192.168.60.2:9003 (RNDIS).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

HEADER_FLAG = 0x8000
HEADER_SIZE = 8
TYPE_HANDSHAKE = 0
TYPE_DATA = 1
TYPE_VIDEO = 2
TYPE_FILE = 3
TYPE_ACK = 4
TYPE_CMD = 5
TYPE_ACK6 = 6

WIFI_PEER = ("192.168.2.1", 9003)
WIRED_PEER = ("192.168.60.2", 9003)
WIRED_LOCAL = "192.168.60.1"

# 48-byte type-0 handshake template observed on the liveview UDP port.
HANDSHAKE_TEMPLATE = bytes.fromhex(
    "30803add00000057"
    "d0e964006400c0051400000a00"
    "64006400c00514000064001400"
    "6400c00514000064000101040a02"
)

VIDEO_HEADER = 0x14  # H.264 starts here in a type-2 packet
SEQ_STEP = 8  # type-2 sequence numbers (low 3 bits stay 0)
SEQ_MASK = 0xFFFF

CMDSET_NAME = {
    0x00: "general",
    0x01: "special",
    0x02: "camera",
    0x03: "flyc",
    0x04: "gimbal",
    0x05: "center",
    0x06: "rc",
    0x07: "wifi",
    0x08: "dm36x",
    0x09: "hdlink",
    0x0A: "vision",
    0x15: "glass",
}

DEVICE_NAME = {
    0x02: "app",
    0x04: "camera",
    0x06: "rc",
    0x08: "gimbal",
    0x09: "hdlink",
    0x0A: "wifi",
    0x1B: "goggles",
}

# Bitrate-hint DUML on MI04: sender 0x1B, receiver 0xEE, cmdset 0x51 cmd 0x29.
# 23-byte payload, kbps at offset 0x13. 22500 kbps / 250 ms is the value
# commonly used by PC liveview clients on this service.
BOOST_KBPS = 22500
BOOST_INTERVAL = 0.25
BOOST_SENDER = 0x1B
BOOST_RECEIVER = 0xEE
BOOST_CMDSET = 0x51
BOOST_CMD = 0x29
_BOOST_PAYLOAD_HEAD = bytes.fromhex("ebfeefbe03000f000201010000000001000000")

_CRC8_TABLE = bytes.fromhex(
    "005ebce2613fdd83c29c7e20a3fd1f419dc3217ffca2401e5f01e3bd3e6082dc"
    "237d9fc1421cfea0e1bf5d0380de3c62bee0025cdf81633d7c22c09e1d43a1ff"
    "4618faa427799bc584da3866e5bb5907db856739bae406581947a5fb7826c49a"
    "653bd987045ab8e6a7f91b45c6987a24f8a6441a99c7257b3a6486d85b05e7b9"
    "8cd2306eedb3510f4e10f2ac2f7193cd114fadf3702ecc92d38d6f31b2ec0e50"
    "aff1134dce90722c6d33d18f0c52b0ee326c8ed0530defb1f0ae4c1291cf2d73"
    "ca947628abf517490856b4ea6937d58b5709ebb536688ad495cb2977f4aa4816"
    "e9b7550b88d6346a2b7597c94a14f6a8742ac896154ba9f7b6e80a54d7896b35"
)
_CRC16_TABLE = struct.unpack(
    "<256H",
    bytes.fromhex(
        "0000891112239b322446ad573665bf74488cc19d5aafd3be6ccae5db7ee9f7f8"
        "8110080193331a22a5562c47b7753e64c99c408ddbbf52aeedda64cbfff976e8"
        "02218b30100299132667af763444bd554aadc3bc588ed19f6eebe7fa7cc8f5d9"
        "83310a2091121803a7772e66b5543c45cbbd42acd99e508feffb66eafdd874c9"
        "04428d5316619f702004a9153227bb364ccec5df5eedd7fc6888e1997aabf3ba"
        "85520c4397711e60a1142805b3373a26cdde44cfdffd56ece9986089fbbb72aa"
        "06638f7214409d512225ab343006b9174eefc7fe5cccd5dd6aa9e3b8788af19b"
        "87730e6295501c41a3352a24b1163807cfff46eedddc54cdebb962a8f99a708b"
        "088481951aa793b62cc2a5d33ee1b7f04008c919522bdb3a644eed5f766dff7c"
        "899400859bb712a6add224c3bff136e0c1184809d33b5a2ae55e6c4ff77d7e6c"
        "0aa583b4188691972ee3a7f23cc0b5d14229cb38500ad91b666fef7e744cfd5d"
        "8bb502a499961087aff326e2bdd034c1c3394a28d11a580be77f6e6ef55c7c4d"
        "0cc685d71ee597f42880a1913aa3b3b2444acd5b5669df78600ce91d722ffb3e"
        "8dd604c79ff516e4a9902081bbb332a2c55a4c4bd7795e68e11c680df33f7a2e"
        "0ee787f61cc495d52aa1a3b03882b193466bcf7a5448dd59622deb3c700ef91f"
        "8ff706e69dd414c5abb122a0b9923083c77b4e6ad5585c49e33d6a2cf11e780f"
    ),
)


def duml_crc8(data: bytes, seed: int = 0x77) -> int:
    value = seed
    for byte in data:
        value = _CRC8_TABLE[(byte ^ value) & 0xFF]
    return value


def duml_crc16(data: bytes, seed: int = 0x3692) -> int:
    value = seed
    for byte in data:
        value = (value >> 8) ^ _CRC16_TABLE[(byte ^ value) & 0xFF]
    return value


def build_duml(sender: int, receiver: int, seq: int, cmdset: int, cmd: int, payload: bytes = b"") -> bytes:
    """DUML v1 (0x55). Same layout the goggles put on type-1 and we put on type-4."""
    length = 13 + len(payload)
    header = bytearray(11)
    header[0] = 0x55
    header[1:3] = struct.pack("<H", (1 << 10) | (length & 0x3FF))
    header[4] = sender & 0xFF
    header[5] = receiver & 0xFF
    header[6:8] = struct.pack("<H", seq & 0xFFFF)
    header[8] = 0
    header[9] = cmdset & 0xFF
    header[10] = cmd & 0xFF
    header[3] = duml_crc8(bytes(header[:3]))
    body = bytes(header) + payload
    return body + struct.pack("<H", duml_crc16(body))


def build_bitrate_boost(seq: int, kbps: int = BOOST_KBPS) -> bytes:
    """DUML bitrate hint written to USB MI04 (kbps little-endian at end of payload)."""
    payload = _BOOST_PAYLOAD_HEAD + struct.pack("<I", kbps & 0xFFFFFFFF)
    return build_duml(BOOST_SENDER, BOOST_RECEIVER, seq, BOOST_CMDSET, BOOST_CMD, payload)


def build_type5(
    session: int,
    seq: int,
    window_start: int,
    window_end: int,
    duml: bytes,
    counter: int = 1,
) -> bytes:
    """Type-5 command packet. Seed/seq step 8, same as type-2 (dji_protocol.md)."""
    body = bytearray()
    body += struct.pack("<HH", window_start & 0xFFFF, window_end & 0xFFFF)
    body += struct.pack("<HH", 0, 0)
    body += bytes([counter & 0xFF, 0x01, 0x00, 0x00])
    body += duml
    packet = bytearray(pack_header(HEADER_SIZE + len(body), session, seq, TYPE_CMD) + body)
    packet[0:2] = struct.pack("<H", (len(packet) & 0x7FFF) | HEADER_FLAG)
    packet[7] = xor7(packet)
    return bytes(packet)


def xor7(data: bytes) -> int:
    value = 0
    for byte in data[:7]:
        value ^= byte
    return value


def pack_header(length: int, session: int, seq: int, packet_type: int) -> bytes:
    raw = struct.pack("<HHHB", (length & 0x7FFF) | HEADER_FLAG, session & 0xFFFF, seq & 0xFFFF, packet_type & 0xFF)
    return raw + bytes([xor7(raw)])


def parse_header(data: bytes) -> dict | None:
    if len(data) < HEADER_SIZE:
        return None
    flagged, session, seq, packet_type = struct.unpack_from("<HHHB", data, 0)
    checksum = data[7]
    length = flagged & 0x7FFF
    if checksum != xor7(data):
        return None
    if length != len(data):
        return None
    return {
        "length": length,
        "flag": bool(flagged & HEADER_FLAG),
        "session": session,
        "seq": seq,
        "type": packet_type,
    }


def build_handshake(session: int) -> bytes:
    packet = bytearray(HANDSHAKE_TEMPLATE)
    packet[2:4] = struct.pack("<H", session & 0xFFFF)
    packet[0:2] = struct.pack("<H", (len(packet) & 0x7FFF) | HEADER_FLAG)
    packet[7] = xor7(packet)
    return bytes(packet)


def handshake_seed(packet: bytes) -> int:
    return struct.unpack_from("<H", packet, 8)[0]


def build_ack(
    session: int,
    window_start: int,
    window_end: int,
    resend: list[int] | tuple[int, ...] = (),
    type3: tuple[int, int] | None = None,
    type5: tuple[int, int] | None = None,
    duml: bytes = b"",
) -> bytes:
    """Type-4 ACK. Type-2 windows follow video; type-3/5 stay on the handshake seed.

    Non-empty ``resend`` lists missing type-2 sequence numbers, in gap order,
    step 8. Optional ``duml`` is appended when the client piggy-backs MB
    commands on the keepalive.
    """
    resend = list(resend)
    t3s, t3e = type3 if type3 is not None else (window_start, window_end)
    t5s, t5e = type5 if type5 is not None else (window_start, window_end)
    body = bytearray()
    body += struct.pack("<HH", window_start & 0xFFFF, window_end & 0xFFFF)
    body += struct.pack("<H", len(resend))
    for seq in resend:
        body += struct.pack("<H", seq & 0xFFFF)
    body += struct.pack("<HHH", t3s & 0xFFFF, t3e & 0xFFFF, 0)
    body += struct.pack("<HHHHH", t5s & 0xFFFF, t5e & 0xFFFF, 0, 0, len(duml) & 0xFFFF)
    body += duml
    packet = bytearray(pack_header(HEADER_SIZE + len(body), session, 0, TYPE_ACK) + body)
    packet[0:2] = struct.pack("<H", (len(packet) & 0x7FFF) | HEADER_FLAG)
    packet[7] = xor7(packet)
    return bytes(packet)


def parse_duml(data: bytes) -> list[dict]:
    """Split DJI MB (DUML) chunks starting with 0x55 from a type-1 tail."""
    chunks: list[dict] = []
    i = 0
    while i + 11 <= len(data):
        if data[i] != 0x55:
            i += 1
            continue
        length = data[i + 1]
        if length < 11 or i + length > len(data):
            i += 1
            continue
        pkt = data[i : i + length]
        payload = pkt[11:-2] if length > 13 else b""
        chunks.append(
            {
                "length": length,
                "version": pkt[2],
                "sender": pkt[4],
                "receiver": pkt[5],
                "seq": struct.unpack_from("<H", pkt, 6)[0],
                "cmd_type": pkt[8],
                "cmdset": pkt[9],
                "cmd": pkt[10],
                "payload": payload,
                "ascii": "".join(chr(b) if 32 <= b < 127 else "." for b in payload),
                "raw": pkt,
            }
        )
        i += length
    return chunks


def parse_data(data: bytes) -> dict | None:
    """Type-1 telemetry. Goggles emit this at ~10 Hz after handshake."""
    header = parse_header(data)
    if header is None or header["type"] != TYPE_DATA or len(data) < 12:
        return None
    parsed = {
        **header,
        "window_start": struct.unpack_from("<H", data, 8)[0],
        "window_end": struct.unpack_from("<H", data, 10)[0],
        "duml": [],
        "serial": "",
    }
    if len(data) >= 0x1C:
        parsed["type3_start"], parsed["type3_end"] = struct.unpack_from("<HH", data, 0x10)
        parsed["type5_start"], parsed["type5_end"] = struct.unpack_from("<HH", data, 0x18)
    if len(data) >= 34:
        duml_len = struct.unpack_from("<H", data, 32)[0]
        blob = data[34 : 34 + duml_len]
        parsed["duml"] = parse_duml(blob)
        for chunk in parsed["duml"]:
            digits = "".join(c if c.isalnum() else " " for c in chunk["ascii"]).split()
            for token in digits:
                if len(token) >= 8:
                    parsed["serial"] = token
                    break
    return parsed


def parse_video(data: bytes) -> dict | None:
    header = parse_header(data)
    if header is None or header["type"] != TYPE_VIDEO or len(data) < VIDEO_HEADER:
        return None
    frame = data[0x10]
    n_parts = data[0x11] & 0x7F
    part = (data[0x11] >> 7) | ((data[0x12] & 0x1F) << 1)
    return {
        **header,
        "window_start": struct.unpack_from("<H", data, 8)[0],
        "window_end": struct.unpack_from("<H", data, 10)[0],
        "frame": frame,
        "n_parts": n_parts,
        "part": part,
        "h264": data[VIDEO_HEADER:],
    }


@dataclass
class FrameAssembler:
    parts: dict[int, bytes] = field(default_factory=dict)
    frame: int | None = None
    n_parts: int = 0
    complete: int = 0

    def push(self, packet: dict) -> bytes | None:
        if packet["n_parts"] <= 0:
            return None
        if self.frame != packet["frame"]:
            self.parts.clear()
            self.frame = packet["frame"]
            self.n_parts = packet["n_parts"]
        self.parts[packet["part"]] = packet["h264"]
        if len(self.parts) < self.n_parts:
            return None
        ordered = [self.parts[i] for i in range(self.n_parts) if i in self.parts]
        if len(ordered) != self.n_parts:
            return None
        self.parts.clear()
        self.complete += 1
        return b"".join(ordered)


def seq_ahead(newer: int, older: int) -> int:
    return (newer - older) & SEQ_MASK


class LossWindow:
    """Type-2 RTX window.

    Sequence numbers step by 8. Missing seqs go in the type-4 ACK resend
    field, in gap order. Retransmit requests must start at the first hole
    or the goggles ignore the whole list.
    """

    def __init__(self, seed: int, max_resend: int = 16):
        self.seed = seed & SEQ_MASK
        self.start = self.seed
        self.end = self.seed
        self.have: set[int] = set()
        self.max_resend = max_resend
        self.armed = False
        self.requests = 0

    def push(self, seq: int) -> list[int]:
        seq &= SEQ_MASK
        if not self.armed:
            self.start = self.end = seq
            self.armed = True
            return []
        self.have.add(seq)
        if 0 < seq_ahead(seq, self.end) < 0x8000:
            self.end = seq
        nxt = (self.start + SEQ_STEP) & SEQ_MASK
        while nxt in self.have:
            self.have.discard(nxt)
            self.start = nxt
            nxt = (self.start + SEQ_STEP) & SEQ_MASK
        stale = [s for s in self.have if seq_ahead(self.end, s) > 2048]
        for s in stale:
            self.have.discard(s)
        return self.missing()

    def missing(self) -> list[int]:
        if not self.armed or self.start == self.end:
            return []
        out: list[int] = []
        cursor = (self.start + SEQ_STEP) & SEQ_MASK
        steps = 0
        stop = (self.end + SEQ_STEP) & SEQ_MASK
        while cursor != stop and len(out) < self.max_resend and steps < 512:
            if cursor not in self.have:
                out.append(cursor)
            cursor = (cursor + SEQ_STEP) & SEQ_MASK
            steps += 1
        if out:
            self.requests += 1
        return out

    def reset(self) -> None:
        self.start = self.end = self.seed
        self.have.clear()
        self.armed = False
