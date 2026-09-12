"""AOA control framing and capture-derived identity replies."""
from __future__ import annotations

from . import duml

AOA_MAGIC = b"\x55\xcc\x30\x75"
VIDEO_MAGIC = b"\x55\xcc\x4a\x57"
AOA_PROTOCOL_VERSION = 2
MOBILE_APP = 2

AOA_STRINGS = {0: "DJI", 1: "com.dji.logiclink", 2: "DJI glass",
               3: "v0.0.0.0", 4: "www.dji.com", 5: "0"}

_IDENTITY_RESPONSES = {
    0x81: bytes.fromhex(
        "0041505000000000000000000000000000000000000000000000000000000000"
        "020000000000000000000000051c000000000000000000000000000000000000"
    ),
    0x82: b"\x00",
    0x88: bytes.fromhex("1a00000000"),
}


def wrap(packet: bytes) -> bytes:
    return AOA_MAGIC + len(packet).to_bytes(4, "little") + packet


def unwrap(buffer: bytearray):
    while True:
        start = buffer.find(AOA_MAGIC)
        if start < 0:
            if len(buffer) > 3:
                del buffer[:-3]
            return
        if start:
            del buffer[:start]
        if len(buffer) < 8:
            return
        length = int.from_bytes(buffer[4:8], "little")
        if length < 13 or length > 1_000_000:
            del buffer[0]
            continue
        total = 8 + length
        if len(buffer) < total:
            return
        packet = bytes(buffer[8:total])
        del buffer[:total]
        if duml.parse(packet) is not None:
            yield packet


def identity_reply(request: bytes) -> bytes | None:
    parsed = duml.parse(request)
    if not parsed or parsed["packet_type"] != 0:
        return None
    if parsed["cmd_set"] != 0 or parsed["cmd_id"] not in _IDENTITY_RESPONSES:
        return None
    return duml.build(
        sender_type=MOBILE_APP,
        receiver_type=parsed["sender_type"],
        seq=parsed["seq"],
        cmd_set=0,
        cmd_id=parsed["cmd_id"],
        payload=_IDENTITY_RESPONSES[parsed["cmd_id"]],
        receiver_idx=parsed["sender_idx"],
        packet_type=1,
    )
