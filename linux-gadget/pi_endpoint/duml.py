"""Small, dependency-free DUML codec used by the standalone endpoint."""
from __future__ import annotations

import struct

CRC8_TABLE = bytes.fromhex(
    """
    005ebce2613fdd83c29c7e20a3fd1f419dc3217ffca2401e5f01e3bd3e6082dc237d9fc1421cfea0e1bf5d0380de3c62
    bee0025cdf81633d7c22c09e1d43a1ff4618faa427799bc584da3866e5bb5907db856739bae406581947a5fb7826c49a
    653bd987045ab8e6a7f91b45c6987a24f8a6441a99c7257b3a6486d85b05e7b98cd2306eedb3510f4e10f2ac2f7193cd
    114fadf3702ecc92d38d6f31b2ec0e50aff1134dce90722c6d33d18f0c52b0ee326c8ed0530defb1f0ae4c1291cf2d73
    ca947628abf517490856b4ea6937d58b5709ebb536688ad495cb2977f4aa4816e9b7550b88d6346a2b7597c94a14f6a8
    742ac896154ba9f7b6e80a54d7896b35
    """
)
CRC16_BYTES = bytes.fromhex(
    """
    0000891112239b322446ad573665bf74488cc19d5aafd3be6ccae5db7ee9f7f88110080193331a22a5562c47b7753e64
    c99c408ddbbf52aeedda64cbfff976e802218b30100299132667af763444bd554aadc3bc588ed19f6eebe7fa7cc8f5d9
    83310a2091121803a7772e66b5543c45cbbd42acd99e508feffb66eafdd874c904428d5316619f702004a9153227bb36
    4ccec5df5eedd7fc6888e1997aabf3ba85520c4397711e60a1142805b3373a26cdde44cfdffd56ece9986089fbbb72aa
    06638f7214409d512225ab343006b9174eefc7fe5cccd5dd6aa9e3b8788af19b87730e6295501c41a3352a24b1163807
    cfff46eedddc54cdebb962a8f99a708b088481951aa793b62cc2a5d33ee1b7f04008c919522bdb3a644eed5f766dff7c
    899400859bb712a6add224c3bff136e0c1184809d33b5a2ae55e6c4ff77d7e6c0aa583b4188691972ee3a7f23cc0b5d1
    4229cb38500ad91b666fef7e744cfd5d8bb502a499961087aff326e2bdd034c1c3394a28d11a580be77f6e6ef55c7c4d
    0cc685d71ee597f42880a1913aa3b3b2444acd5b5669df78600ce91d722ffb3e8dd604c79ff516e4a9902081bbb332a2
    c55a4c4bd7795e68e11c680df33f7a2e0ee787f61cc495d52aa1a3b03882b193466bcf7a5448dd59622deb3c700ef91f
    8ff706e69dd414c5abb122a0b9923083c77b4e6ad5585c49e33d6a2cf11e780f
    """
)
CRC16_TABLE = tuple(struct.unpack("<256H", CRC16_BYTES))


def crc8(data: bytes, seed: int = 0x77) -> int:
    value = seed
    for byte in data:
        value = CRC8_TABLE[(byte ^ value) & 0xFF]
    return value


def crc16(data: bytes, seed: int = 0x3692) -> int:
    value = seed
    for byte in data:
        value = (value >> 8) ^ CRC16_TABLE[(byte ^ value) & 0xFF]
    return value


def build(sender_type: int, receiver_type: int, seq: int, cmd_set: int,
          cmd_id: int, payload: bytes = b"", *, sender_idx: int = 0,
          receiver_idx: int = 0, packet_type: int = 0, ack_type: int = 0,
          enc_type: int = 0, version: int = 1) -> bytes:
    length = 13 + len(payload)
    ver_len = (version << 10) | (length & 0x3FF)
    header = bytearray(11)
    header[0] = 0x55
    header[1:3] = struct.pack("<H", ver_len)
    header[4] = (sender_type & 0x1F) | ((sender_idx & 7) << 5)
    header[5] = (receiver_type & 0x1F) | ((receiver_idx & 7) << 5)
    header[6:8] = struct.pack("<H", seq & 0xFFFF)
    header[8] = ((packet_type & 1) << 7) | ((ack_type & 3) << 5) | (enc_type & 7)
    header[9] = cmd_set & 0xFF
    header[10] = cmd_id & 0xFF
    header[3] = crc8(bytes(header[:3]))
    body = bytes(header) + payload
    return body + struct.pack("<H", crc16(body))


def parse(packet: bytes) -> dict | None:
    if len(packet) < 13 or packet[0] != 0x55:
        return None
    ver_len = packet[1] | (packet[2] << 8)
    length = ver_len & 0x3FF
    if length != len(packet) or crc8(packet[:3]) != packet[3]:
        return None
    if crc16(packet[:-2]) != struct.unpack_from("<H", packet, len(packet) - 2)[0]:
        return None
    return {
        "version": ver_len >> 10,
        "length": length,
        "sender_type": packet[4] & 0x1F,
        "sender_idx": (packet[4] >> 5) & 7,
        "receiver_type": packet[5] & 0x1F,
        "receiver_idx": (packet[5] >> 5) & 7,
        "seq": packet[6] | (packet[7] << 8),
        "packet_type": packet[8] >> 7,
        "ack_type": (packet[8] >> 5) & 3,
        "cmd_set": packet[9],
        "cmd_id": packet[10],
        "payload": packet[11:-2],
    }
