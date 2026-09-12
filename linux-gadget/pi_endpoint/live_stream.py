"""Fan-out the live H.264 bitstream as fragmented MP4 for the dashboard.

The HDMI path already hardware-decodes for kmssink. This hub never decodes or
re-encodes: it remuxes Annex-B into fMP4 so a browser can play the same
quality with Media Source Extensions.
"""
from __future__ import annotations

import os
import queue
import socket
import struct
import threading
import time
from pathlib import Path


NAL_NON_IDR = 1
NAL_IDR = 5
NAL_SPS = 7
NAL_PPS = 8
NAL_AUD = 9
TIMESCALE = 90_000
DEFAULT_SAMPLE_DURATION = 3_000          
MAX_CLIENTS = 3
CLIENT_QUEUE = 36
MAX_GOP_FRAGMENTS = 90


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def full_box(kind: bytes, version_flags: int, payload: bytes = b"") -> bytes:
    return box(kind, struct.pack(">I", version_flags) + payload)


def nal_type(nal: bytes) -> int:
    return nal[0] & 0x1F if nal else 0


def to_avcc(nals: list[bytes]) -> bytes:
    return b"".join(struct.pack(">I", len(nal)) + nal for nal in nals if nal)


def codec_from_sps(sps: bytes) -> str:
    if len(sps) < 4:
        return "avc1.42E01E"
    return f"avc1.{sps[1]:02X}{sps[2]:02X}{sps[3]:02X}"


def avcc_box(sps: bytes, pps: bytes) -> bytes:
    payload = bytes((1, sps[1], sps[2], sps[3], 0xFF, 0xE1))
    payload += struct.pack(">H", len(sps)) + sps + bytes((1,))
    payload += struct.pack(">H", len(pps)) + pps
    return box(b"avcC", payload)


class AnnexBParser:
    """Split a byte-stream into complete NAL payloads (start codes removed)."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[bytes]:
        if data:
            self._buffer.extend(data)
        completed: list[bytes] = []
        while True:
            start, start_len = self._next_start(0)
            if start < 0:
                if len(self._buffer) > 3:
                    del self._buffer[:-3]
                return completed
            if start:
                del self._buffer[:start]
                start, start_len = 0, self._start_len(0)
            next_start, _ = self._next_start(start_len)
            if next_start < 0:
                if len(self._buffer) > 8 * 1024 * 1024:
                    self._buffer.clear()
                return completed
            nal = bytes(self._buffer[start_len:next_start])
            del self._buffer[:next_start]
            if nal:
                completed.append(nal)

    def _start_len(self, offset: int) -> int:
        if self._buffer[offset:offset + 4] == b"\x00\x00\x00\x01":
            return 4
        return 3

    def _next_start(self, offset: int) -> tuple[int, int]:
        index = self._buffer.find(b"\x00\x00\x01", offset)
        if index < 0:
            return -1, 0
        if index > offset and self._buffer[index - 1] == 0:
            return index - 1, 4
        return index, 3


class AccessUnitAssembler:
    """Group NALs into access units using AUD / VCL boundaries."""

    def __init__(self) -> None:
        self._nals: list[bytes] = []
        self._has_vcl = False

    def reset(self) -> None:
        self._nals = []
        self._has_vcl = False

    def push(self, nal: bytes) -> list[bytes] | None:
        if not nal:
            return None
        kind = nal_type(nal)
        if kind == NAL_AUD and self._nals:
            completed = self._nals
            self._nals = [nal]
            self._has_vcl = False
            return completed
                                                                   
                                                                        
        if kind in {NAL_IDR, NAL_NON_IDR} and self._has_vcl and len(nal) > 1 and nal[1] & 0x80:
            completed = self._nals
            self._nals = [nal]
            self._has_vcl = True
            return completed
        self._nals.append(nal)
        if kind in {NAL_IDR, NAL_NON_IDR}:
            self._has_vcl = True
        return None


class Fmp4Muxer:
    def __init__(self) -> None:
        self.sps = b""
        self.pps = b""
        self.init = b""
        self.codec = "avc1.42E01E"
        self.sequence = 1
        self.decode_time = 0
        self.last_au_at = 0.0

    def reset(self) -> None:
        self.sequence = 1
        self.decode_time = 0
        self.last_au_at = 0.0

    def set_parameter_sets(self, sps: bytes, pps: bytes) -> bool:
        if not sps or not pps or (sps == self.sps and pps == self.pps and self.init):
            return False
        self.sps = sps
        self.pps = pps
        self.codec = codec_from_sps(sps)
        self.init = self._init_segment()
        self.reset()
        return True

    def fragment(self, nals: list[bytes], keyframe: bool) -> bytes:
        sample = to_avcc(nals)
        if not sample or not self.init:
            return b""
        duration = self._duration()
        flags = 0x02000000 if keyframe else 0x01010000
        mfhd = full_box(b"mfhd", 0, struct.pack(">I", self.sequence))
        tfhd = full_box(b"tfhd", 0x00020000, struct.pack(">I", 1))
        tfdt = full_box(b"tfdt", 0x01000000, struct.pack(">Q", self.decode_time))
        trun_inner = struct.pack(">IIIII", 1, 0, duration, len(sample), flags)
        trun = full_box(b"trun", 0x00000701, trun_inner)
        traf = box(b"traf", tfhd + tfdt + trun)
        moof = box(b"moof", mfhd + traf)
        offset = len(moof) + 8
        moof = bytearray(moof)
        trun_offset = moof.find(b"trun")
        struct.pack_into(">I", moof, trun_offset + 12, offset)
        self.sequence += 1
        self.decode_time += duration
        return bytes(moof) + box(b"mdat", sample)

    def _duration(self) -> int:
        now = time.monotonic()
        duration = DEFAULT_SAMPLE_DURATION
        if self.last_au_at:
            measured = int((now - self.last_au_at) * TIMESCALE)
            if 1200 <= measured <= 4800:
                duration = measured
        self.last_au_at = now
        return duration

    def _init_segment(self) -> bytes:
        width, height = 1920, 1080
        identity = struct.pack(">9I", 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)
        ftyp = box(b"ftyp", b"iso5" + struct.pack(">I", 512) + b"iso6mp41iso5dash")
        mvhd = full_box(
            b"mvhd",
            0,
            struct.pack(">IIII", 0, 0, TIMESCALE, 0)
            + struct.pack(">IH", 0x00010000, 0x0100)
            + b"\x00" * 10
            + identity
            + b"\x00" * 24
            + struct.pack(">I", 2),
        )
        tkhd = full_box(
            b"tkhd",
            0x00000003,
            struct.pack(">IIIII", 0, 0, 1, 0, 0)
            + b"\x00" * 8
            + struct.pack(">HHHH", 0, 0, 0, 0)
            + identity
            + struct.pack(">II", width << 16, height << 16),
        )
        mdhd = full_box(
            b"mdhd",
            0,
            struct.pack(">IIII", 0, 0, TIMESCALE, 0) + struct.pack(">HH", 0x55C4, 0),
        )
        hdlr = full_box(b"hdlr", 0, b"\x00" * 4 + b"vide" + b"\x00" * 12 + b"VideoHandler\x00")
        vmhd = full_box(b"vmhd", 1, struct.pack(">HHH", 0, 0, 0))
        url = full_box(b"url ", 1)
        dref = full_box(b"dref", 0, struct.pack(">I", 1) + url)
        dinf = box(b"dinf", dref)
        avc1 = box(
            b"avc1",
            b"\x00" * 6
            + struct.pack(">H", 1)
            + struct.pack(">HH", 0, 0)
            + b"\x00" * 12
            + struct.pack(">HH", width, height)
            + struct.pack(">II", 0x00480000, 0x00480000)
            + struct.pack(">I", 0)
            + struct.pack(">H", 1)
            + b"\x00" * 32
            + struct.pack(">HH", 0x0018, 0xFFFF)
            + avcc_box(self.sps, self.pps),
        )
        stsd = full_box(b"stsd", 0, struct.pack(">I", 1) + avc1)
        stts = full_box(b"stts", 0, struct.pack(">I", 0))
        stsc = full_box(b"stsc", 0, struct.pack(">I", 0))
        stsz = full_box(b"stsz", 0, struct.pack(">II", 0, 0))
        stco = full_box(b"stco", 0, struct.pack(">I", 0))
        stbl = box(b"stbl", stsd + stts + stsc + stsz + stco)
        minf = box(b"minf", vmhd + dinf + stbl)
        mdia = box(b"mdia", mdhd + hdlr + minf)
        trak = box(b"trak", tkhd + mdia)
        trex = full_box(b"trex", 0, struct.pack(">5I", 1, 1, 0, 0, 0x01010000))
        mvex = box(b"mvex", trex)
        moov = box(b"moov", mvhd + trak + mvex)
        return ftyp + moov


class LiveStreamHub:
    """Unix-socket fMP4 publisher. ``push()`` never blocks USB/HDMI."""

    def __init__(self, path: str | None, max_clients: int = MAX_CLIENTS):
        self.path = Path(path) if path else None
        self.max_clients = max_clients
        self.parser = AnnexBParser()
        self.assembler = AccessUnitAssembler()
        self.muxer = Fmp4Muxer()
        self.lock = threading.Lock()
        self.clients: list[queue.Queue[bytes | None]] = []
        self.gop: list[bytes] = []
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.listener: socket.socket | None = None
        self.last_error = ""
        self.access_units = 0
        self.keyframes = 0
        self.input_queue: queue.Queue[bytes] = queue.Queue(maxsize=128)
        self.reset_pending = threading.Event()
        self.worker: threading.Thread | None = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.thread = threading.Thread(target=self._serve, name="live-fmp4", daemon=True)
            self.thread.start()
            self.worker = threading.Thread(target=self._consume, name="live-remux", daemon=True)
            self.worker.start()

    def _serve(self) -> None:
        try:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(self.path))
            os.chmod(self.path, 0o660)
            listener.listen(self.max_clients)
            listener.settimeout(0.25)
            self.listener = listener
        except OSError as error:
            self.last_error = str(error)
            return
        while not self.stop_event.is_set():
            try:
                connection, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError as error:
                if not self.stop_event.is_set():
                    self.last_error = str(error)
                return
            threading.Thread(target=self._client, args=(connection,), daemon=True).start()

    def _client(self, connection: socket.socket) -> None:
        pending: queue.Queue[bytes | None] = queue.Queue(maxsize=CLIENT_QUEUE)
        try:
            connection.settimeout(20)
            deadline = time.monotonic() + 20
            while not self.stop_event.is_set():
                with self.lock:
                    if len(self.clients) >= self.max_clients:
                        return
                    init = self.muxer.init
                    startup = list(self.gop)
                    if init and startup:
                        self.clients.append(pending)
                        break
                if time.monotonic() >= deadline:
                    return
                self.stop_event.wait(0.05)
            else:
                return
            connection.sendall(init)
            for fragment in startup:
                connection.sendall(fragment)
            while not self.stop_event.is_set():
                try:
                    item = pending.get(timeout=0.5)
                except queue.Empty:
                    continue
                if item is None:
                    return
                connection.sendall(item)
        except OSError as error:
            self.last_error = str(error)
        finally:
            with self.lock:
                if pending in self.clients:
                    self.clients.remove(pending)
            try:
                connection.close()
            except OSError:
                pass

    def _on_access_unit(self, nals: list[bytes]) -> None:
        sps = next((nal for nal in nals if nal_type(nal) == NAL_SPS), None)
        pps = next((nal for nal in nals if nal_type(nal) == NAL_PPS), None)
        slices = [nal for nal in nals if nal_type(nal) in {NAL_IDR, NAL_NON_IDR}]
        keyframe = any(nal_type(nal) == NAL_IDR for nal in slices)
        with self.lock:
            changed = False
            if sps and (pps or self.muxer.pps):
                changed = self.muxer.set_parameter_sets(sps, pps or self.muxer.pps)
            elif pps and self.muxer.sps:
                changed = self.muxer.set_parameter_sets(self.muxer.sps, pps)
            if changed:
                self.gop = []
                for pending in self.clients:
                    while not pending.empty():
                        try:
                            pending.get_nowait()
                        except queue.Empty:
                            break
                    pending.put_nowait(None)
                self.clients.clear()
            if not slices:
                return
            fragment = self.muxer.fragment(nals, keyframe)
            if not fragment:
                return
            self.access_units += 1
            if keyframe:
                self.keyframes += 1
                self.gop = [fragment]
            elif self.gop and len(self.gop) < MAX_GOP_FRAGMENTS:
                self.gop.append(fragment)
            elif self.gop:
                self.gop = []
            clients = list(self.clients)
        for pending in clients:
            try:
                pending.put_nowait(fragment)
            except queue.Full:
                try:
                    while True:
                        pending.get_nowait()
                except queue.Empty:
                    pass
                pending.put_nowait(None)

    def push(self, data: bytes) -> None:
        if not self.path or self.stop_event.is_set() or not data:
            return
        try:
            self.input_queue.put_nowait(data)
        except queue.Full:
            self.reset_pending.set()
            self.last_error = "preview queue overflow; awaiting clean stream"

    def _consume(self) -> None:
        while not self.stop_event.is_set():
            if self.reset_pending.is_set():
                self.parser.reset()
                self.assembler.reset()
                self.muxer.reset()
                with self.lock:
                    self.gop = []
                    clients = list(self.clients)
                for pending in clients:
                    try:
                        while True:
                            pending.get_nowait()
                    except queue.Empty:
                        pass
                    pending.put_nowait(None)
                try:
                    while True:
                        self.input_queue.get_nowait()
                except queue.Empty:
                    pass
                self.reset_pending.clear()
            try:
                data = self.input_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            self._parse(data)

    def _parse(self, data: bytes) -> None:
        try:
            for nal in self.parser.feed(data):
                assembled = self.assembler.push(nal)
                if assembled:
                    self._on_access_unit(assembled)
        except Exception as error:                                                      
            self.last_error = str(error)

    def reset(self) -> None:
        self.reset_pending.set()

    def status(self) -> dict:
        with self.lock:
            viewers = len(self.clients)
        return {
            "live_configured": bool(self.path),
            "live_viewers": viewers,
            "live_codec": self.muxer.codec if self.muxer.init else "",
            "live_ready": bool(self.muxer.init),
            "live_access_units": self.access_units,
            "live_error": self.last_error,
        }

    def close(self) -> None:
        self.stop_event.set()
        with self.lock:
            clients = list(self.clients)
            self.clients.clear()
        for pending in clients:
            try:
                pending.put_nowait(None)
            except queue.Full:
                pass
        listener = self.listener
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if self.thread:
            self.thread.join(timeout=1)
        if self.worker:
            self.worker.join(timeout=1)
        if self.path:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
