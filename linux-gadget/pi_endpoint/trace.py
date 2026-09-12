"""Low-overhead diagnostics for a real goggles↔Pi session.

Text logs contain protocol metadata and complete DUML control packets. Video is
logged as framing metadata plus a short preview; optional raw bulk capture is
bounded by a user-selected byte limit.
"""
from __future__ import annotations

import platform
import threading
import time
from pathlib import Path

from . import aoa, duml


def _hex(data: bytes, limit: int = 64) -> str:
    if len(data) <= limit:
        return data.hex()
    return f"{data[:limit].hex()}...(+{len(data) - limit}B)"


def _now() -> str:
    return f"{time.time():.6f} mono={time.monotonic():.6f}"


class TraceLogger:
    def __init__(self, directory: str, *, capture_raw: bool = False,
                 raw_limit_mb: int = 32, video_every: int = 1,
                 log_limit_mb: int = 32):
        self.directory = Path(directory).expanduser()
        self.directory.mkdir(parents=True, exist_ok=True)
        self._paths = {
            name: self.directory / f"{name}.log"
            for name in ("session", "ep0", "bulk_in", "bulk_out", "video", "errors")
        }
        self._files = {
            name: path.open("a", buffering=1)
            for name, path in self._paths.items()
        }
        self._log_limit = max(0, log_limit_mb) * 1024 * 1024
        self._raw = None
        self._raw_limit = max(0, raw_limit_mb) * 1024 * 1024
        self._raw_written = 0
        self._lock = threading.Lock()
        self.video_every = max(1, video_every)
        self.video_count = 0
        self.bulk_out_count = 0
        self.bulk_in_count = 0
        if capture_raw and self._raw_limit:
            self._raw = (self.directory / "bulk_out.raw").open("ab", buffering=0)
        self.event("logger", f"platform={platform.platform()} python={platform.python_version()} "
                              f"raw_capture={bool(self._raw)} raw_limit={self._raw_limit}")

    def _write(self, stream: str, message: str) -> None:
        line = f"{_now()} {message}\n"
        with self._lock:
            handle = self._files[stream]
            if self._log_limit and handle.tell() + len(line.encode()) > self._log_limit:
                handle.close()
                rotated = self._paths[stream].with_name(self._paths[stream].name + ".1")
                try:
                    rotated.unlink()
                except FileNotFoundError:
                    pass
                self._paths[stream].replace(rotated)
                handle = self._paths[stream].open("a", buffering=1)
                self._files[stream] = handle
            handle.write(line)

    def event(self, kind: str, message: str) -> None:
        self._write("session", f"{kind} {message}")

    def error(self, message: str) -> None:
        self._write("errors", message)
        self.event("ERROR", message)

    def ep0_request(self, request: dict, raw: bytes) -> None:
        self._write(
            "ep0",
            "request "
            f"type=0x{request['type']:02x} req=0x{request['request']:02x} "
            f"value=0x{request['value']:04x} index=0x{request['index']:04x} "
            f"length={request['length']} raw={raw.hex()}",
        )

    def ep0_response(self, length: int, data: bytes = b"", note: str = "") -> None:
        self._write("ep0", f"response length={length} actual={len(data)} note={note} hex={_hex(data)}")

    @staticmethod
    def _duml_description(data: bytes) -> str:
        if not data.startswith(aoa.AOA_MAGIC) or len(data) < 8:
            return ""
        length = int.from_bytes(data[4:8], "little")
        packet = data[8:8 + length]
        parsed = duml.parse(packet)
        if not parsed:
            return f"aoa_len={length} duml=invalid"
        return (
            f"aoa_len={length} duML="
            f"type={parsed['packet_type']} ack={parsed['ack_type']} "
            f"seq={parsed['seq']} sender={parsed['sender_type']}:{parsed['sender_idx']} "
            f"receiver={parsed['receiver_type']}:{parsed['receiver_idx']} "
            f"cs={parsed['cmd_set']} cid=0x{parsed['cmd_id']:02x} "
            f"payload_len={len(parsed['payload'])} payload={parsed['payload'].hex()}"
        )

    def bulk_in(self, endpoint: int | None, data: bytes, note: str = "") -> None:
        self.bulk_in_count += 1
        if len(data) >= 256 and self.bulk_in_count % 1000:
            return
        self._write(
            "bulk_in",
            f"packet={self.bulk_in_count} ep={endpoint} length={len(data)} note={note} "
            f"{self._duml_description(data)} hex={_hex(data, 32)}",
        )

    def bulk_out(self, endpoint: int | None, data: bytes) -> None:
        self.bulk_out_count += 1
        if len(data) >= 256 and self.bulk_out_count % 1000:
            if self._raw is not None and self._raw_written < self._raw_limit:
                remaining = self._raw_limit - self._raw_written
                chunk = data[:remaining]
                self._raw.write(chunk)
                self._raw_written += len(chunk)
            return
        self._write(
            "bulk_out",
            f"read={self.bulk_out_count} ep={endpoint} length={len(data)} "
            f"has_video={aoa.VIDEO_MAGIC in data} has_aoa={aoa.AOA_MAGIC in data} "
            f"hex={_hex(data, 32)}",
        )
        if self._raw is not None and self._raw_written < self._raw_limit:
            remaining = self._raw_limit - self._raw_written
            chunk = data[:remaining]
            self._raw.write(chunk)
            self._raw_written += len(chunk)

    def control_packet(self, direction: str, packet: bytes, note: str = "") -> None:
        parsed = duml.parse(packet)
        stream = "bulk_in" if direction == "out" else "bulk_out"
        if parsed is None:
            self._write(stream, f"control direction={direction} invalid note={note} hex={_hex(packet)}")
            return
        self._write(
            stream,
            f"control direction={direction} note={note} length={len(packet)} "
            f"seq={parsed['seq']} sender={parsed['sender_type']}:{parsed['sender_idx']} "
            f"receiver={parsed['receiver_type']}:{parsed['receiver_idx']} "
            f"ack={parsed['ack_type']} type={parsed['packet_type']} "
            f"cmd_set=0x{parsed['cmd_set']:02x} cmd_id=0x{parsed['cmd_id']:02x} "
            f"payload={parsed['payload'].hex()} hex={_hex(packet)}",
        )

    def video(self, payload: bytes, stats: dict) -> None:
        self.video_count += 1
        if self.video_count % self.video_every:
            return
        nals = []
        for marker in (b"\x00\x00\x00\x01", b"\x00\x00\x01"):
            pos = 0
            while True:
                pos = payload.find(marker, pos)
                if pos < 0:
                    break
                header = pos + len(marker)
                if header < len(payload):
                    nals.append(payload[header] & 0x1F)
                pos = header
        rate_bytes = stats.get("payload_bytes", 0)
        self._write(
            "video",
            f"chunk={self.video_count} payload_len={len(payload)} total_bytes={rate_bytes} "
            f"nals={nals[:32]} head={_hex(payload, 32)}",
        )

    def close(self) -> None:
        self.event("summary", f"bulk_in={self.bulk_in_count} bulk_out={self.bulk_out_count} "
                              f"video_chunks={self.video_count} raw_written={self._raw_written}")
        with self._lock:
            if self._raw is not None:
                self._raw.close()
            for handle in self._files.values():
                handle.close()
