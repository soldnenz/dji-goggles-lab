"""Streaming parser for the goggles' bulk video framing."""
from __future__ import annotations

import struct

VIDEO_MAGIC = b"\x55\xcc\x4a\x57"
MAX_PAYLOAD = 2_000_000


class VideoDeframer:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.chunks = 0
        self.bytes = 0
        self.resyncs = 0

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self._buffer.extend(data)
        completed: list[bytes] = []
        while True:
            start = self._buffer.find(VIDEO_MAGIC)
            if start < 0:
                if len(self._buffer) > 3:
                    del self._buffer[:-3]
                return completed
            if start:
                del self._buffer[:start]
                self.resyncs += 1
            if len(self._buffer) < 8:
                return completed
            length = struct.unpack_from("<I", self._buffer, 4)[0]
            if length == 0 or length > MAX_PAYLOAD:
                del self._buffer[0]
                self.resyncs += 1
                continue
            total = 8 + length
            if len(self._buffer) < total:
                return completed
            payload = bytes(self._buffer[8:total])
            del self._buffer[:total]
            self.chunks += 1
            self.bytes += len(payload)
            completed.append(payload)

    def stats(self) -> dict:
        return {"chunks": self.chunks, "payload_bytes": self.bytes,
                "buffered": len(self._buffer), "resyncs": self.resyncs}


def first_sps(data: bytes) -> int | None:
    for marker in (b"\x00\x00\x00\x01\x67", b"\x00\x00\x01\x67"):
        position = data.find(marker)
        if position >= 0:
            return position
    return None
