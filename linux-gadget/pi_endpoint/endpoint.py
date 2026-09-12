                      
"""Pi-side endpoint: AOA handshake, DUML identity/keepalive and video."""
from __future__ import annotations

import argparse
import json
from collections import deque
import errno
import os
import queue
import shlex
import signal
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import aoa, duml, camera_control
from .control_server import ControlServer, DEFAULT_SOCKET
from .raw_gadget import (
    AOA_GET_PROTOCOL, AOA_SEND_STRING, AOA_START, AOA_PROTOCOL_VERSION,
    PID_ACCESSORY, PID_NORMAL, USB_DIR_IN, USB_TYPE_MASK, USB_TYPE_STANDARD,
    USB_TYPE_VENDOR, USB_REQ_GET_DESCRIPTOR, USB_REQ_GET_CONFIGURATION,
    USB_REQ_SET_CONFIGURATION, USB_REQ_GET_INTERFACE, USB_REQ_SET_INTERFACE,
    USB_REQ_SET_ADDRESS, USB_REQ_GET_STATUS, USB_DT_DEVICE, USB_DT_CONFIG,
    USB_DT_STRING, USB_DT_DEVICE_QUALIFIER, USB_DT_OTHER_SPEED_CONFIG,
    USB_DT_BOS, USB_RAW_EVENT_CONNECT, USB_RAW_EVENT_CONTROL,
    USB_RAW_EVENT_RESET, USB_RAW_EVENT_DISCONNECT, RawGadget,
    config_descriptor, device_descriptor, parse_control, qualifier_descriptor,
    string_descriptor,
)
from .video import VideoDeframer, first_sps
from .trace import TraceLogger
from .output_profile import DEFAULT_SETTINGS_PATH, build_command, build_fallback_command, describe, resolve_fallback_video, supervised_command
from .preview import PreviewEncoder
from .live_stream import LiveStreamHub

DESCRIPTOR_STRINGS = {1: "DJI", 2: "com.dji.logiclink", 3: "0123456789ABCDEF"}
STOP = threading.Event()


class VideoOutput:
    """Write H.264 without allowing a broken HDMI sink to stop USB capture.

    ``kmssink`` can block in the kernel while a connector is renegotiating or
    the display driver is recovering.  The old implementation wrote to the
    player's blocking pipe from a worker and never restarted the player.  A
    stalled player then accumulated back-pressure and made recovery depend on
    manually restarting the whole endpoint.

    The player is now supervised separately.  Its stdin is non-blocking; data
    that cannot be consumed quickly is dropped and the player is restarted.
    The raw H.264 dump remains independent and is never fed through the HDMI
    process, so a display failure cannot stop USB reception.
    """

                                                                            
                                                                          
                                                                            
    PLAYER_QUEUE_SIZE = 128
    PLAYER_BLOCK_TIMEOUT = 0.75
    PLAYER_RESTART_DELAY = 0.5

    def __init__(self, output: str | None, player_cmd: str | None,
                 display_status: str | None = None,
                 settings_path: str | None = DEFAULT_SETTINGS_PATH,
                 preview_path: str | None = None,
                 fallback_video: str | None = None,
                 live_socket: str | None = None):
        self.file = open(output, "wb", buffering=1024 * 1024) if output else None
        self.base_command = shlex.split(player_cmd) if player_cmd else None
        self.settings_path = settings_path
        self.command, self.profile = build_command(self.base_command, settings_path)
        self.fallback_video = resolve_fallback_video(fallback_video)
        self.fallback_command, _ = build_fallback_command(self.base_command, settings_path, self.fallback_video)
        self.display_status = display_status
        self.process: subprocess.Popen | None = None
        self.process_kind: str | None = None
        self.queue: queue.Queue[bytes | None] = queue.Queue(maxsize=self.PLAYER_QUEUE_SIZE)
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.dropped = 0
        self.restarts = 0
        self.last_player_error = ""
        self.last_file_error = ""
        self.data_seen = threading.Event()
        self.display_reset = threading.Event()
        self.player_stuck = False
        self.decoder_reset = threading.Event()
        self.wait_sps = False
        self.sps_tail = b""
        self.preview = PreviewEncoder(preview_path)
        self.live = LiveStreamHub(live_socket)
        if self.command:
            self.thread = threading.Thread(target=self._player_loop, name="video-player", daemon=True)
            self.thread.start()

    def _stop_process(self, wait_timeout: float = 0.5) -> bool:
        with self.lock:
            process = self.process
        if process is None:
            with self.lock:
                self.process_kind = None
            return True
        try:
            if process.stdin is not None:
                process.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            process.terminate()
            process.wait(timeout=wait_timeout)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=wait_timeout)
            except (OSError, subprocess.TimeoutExpired):
                                                                            
                                                                             
                                                                           
                                                                             
                                                                    
                self.last_player_error = "player stuck in kernel; suppressing restart"
                with self.lock:
                    self.process = process
                    self.player_stuck = True
                return False
        with self.lock:
            if self.process is process:
                self.process = None
                self.process_kind = None
            self.player_stuck = False
        return True

    def _start_process(self, command: list[str], kind: str) -> bool:
        if not command or self.stop_event.is_set():
            return False
        try:
                                                                             
                                                        
            if "kmssink" in command:
                if kind == "fallback":
                    command, _ = build_fallback_command(self.base_command, self.settings_path, self.fallback_video)
                else:
                    command, _ = build_command(self.base_command, self.settings_path)
            command = supervised_command(command, loop=kind == "fallback", fallback=self.fallback_video)
            environment = dict(os.environ)
            environment.pop("NOTIFY_SOCKET", None)
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE if kind == "live" else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=None,
                env=environment,
                close_fds=True,
            )
            if kind == "live" and process.stdin is None:
                process.terminate()
                return False
            if kind == "live":
                os.set_blocking(process.stdin.fileno(), False)
            with self.lock:
                self.process = process
                self.process_kind = kind
                self.player_stuck = False
                self.restarts += 1
                self.last_player_error = ""
            return True
        except (OSError, ValueError) as error:
            self.last_player_error = str(error)
            return False

    def reload_profile(self) -> dict:
        """Reload conversion settings without touching the USB session."""
        command, profile = build_command(self.base_command, self.settings_path)
        fallback_command, _ = build_fallback_command(self.base_command, self.settings_path, self.fallback_video)
        with self.lock:
            self.command = command
            self.fallback_command = fallback_command
            self.profile = profile
        self.data_seen.clear()
        self._clear_queue()
        stopped = self._stop_process(wait_timeout=0.25)
        self.display_reset.set()
        if not stopped:
            profile = {**profile, "applied": False, "reason": "player stuck in kernel"}
        return {"profile": profile, "player_stopped": stopped}

    def _clear_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                return

    def _display_connected(self) -> bool:
        if not self.display_status:
            return True
        paths = [item.strip() for item in self.display_status.split(",") if item.strip()]
        seen = False
        for path in paths:
            try:
                status = Path(path).read_text(encoding="ascii").strip().lower()
                seen = True
                if status == "connected":
                    return True
            except OSError:
                continue
                                                                           
                                                             
        return True if not seen else False

    def consume_display_reset(self) -> bool:
        if not self.display_reset.is_set():
            return False
        self.display_reset.clear()
        return True

    def _player_loop(self) -> None:
        pending = bytearray()
        blocked_since: float | None = None
        next_start = 0.0
        while not self.stop_event.is_set():
            now = time.monotonic()
            if self.decoder_reset.is_set():
                self._clear_queue()
                pending.clear()
                self.wait_sps = True
                self.sps_tail = b""
                with self.lock:
                    current = self.process
                if current is not None and current.poll() is None:
                    try:
                        current.send_signal(signal.SIGUSR1)
                    except ProcessLookupError:
                        pass
                self.decoder_reset.clear()
            with self.lock:
                process = self.process
                process_kind = self.process_kind
                player_stuck = self.player_stuck
            if not self._display_connected():
                if process is not None:
                    self._stop_process(wait_timeout=0.25)
                    self._clear_queue()
                    pending.clear()
                    self.data_seen.clear()
                    self.display_reset.set()
                time.sleep(0.05)
                continue
            if process is not None and process.poll() is not None:
                with self.lock:
                    if self.process is process:
                        self.process = None
                        self.process_kind = None
                    self.player_stuck = False
                self.last_player_error = f"{process_kind} player exited rc={process.returncode}"
                next_start = now + self.PLAYER_RESTART_DELAY
                process = None
                process_kind = None
                player_stuck = False
            if player_stuck:
                                                                            
                                                                            
                                                                 
                time.sleep(0.2)
                continue
            if process is None or process.poll() is not None:
                if process is not None:
                    if process_kind != "fallback":
                        self.last_player_error = f"player exited rc={process.returncode}"
                    self._stop_process()
                    self._clear_queue()
                    next_start = now + (0.05 if process_kind == "fallback" else self.PLAYER_RESTART_DELAY)
                                                                          
                                                                              
                start_kind = "live"
                start_command = self.command if start_kind == "live" else self.fallback_command
                if not start_command:
                    time.sleep(0.05)
                    continue
                if now >= next_start and self._start_process(start_command, start_kind):
                    process_kind = start_kind
                    pending.clear()
                    blocked_since = None
                else:
                    time.sleep(0.05)
                    continue

                                                                            
                                                                             
                                                             
            if process_kind == "fallback" and self.data_seen.is_set():
                stopped = self._stop_process(wait_timeout=0.25)
                pending.clear()
                blocked_since = None
                next_start = now if stopped else now + self.PLAYER_RESTART_DELAY
                if not stopped:
                    self.player_stuck = True
                continue

            if process_kind == "fallback":
                time.sleep(0.05)
                continue

            if not pending:
                try:
                    item = self.queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                if item is None:
                    break
                pending.extend(item)

            with self.lock:
                process = self.process
                stdin = process.stdin if process is not None else None
            if stdin is None:
                pending.clear()
                continue
            try:
                written = os.write(stdin.fileno(), pending)
                if written:
                    del pending[:written]
                    blocked_since = None
            except BlockingIOError:
                                                                               
                                                                                
                                                                 
                if blocked_since is None:
                    blocked_since = time.monotonic()
                time.sleep(0.002)
            except (BrokenPipeError, OSError, ValueError) as error:
                self.last_player_error = str(error)
                stopped = self._stop_process()
                self._clear_queue()
                pending.clear()
                blocked_since = None
                next_start = time.monotonic() + self.PLAYER_RESTART_DELAY
                if not stopped:
                    self.player_stuck = True

        self._stop_process()

    def push(self, data: bytes) -> None:
        self.data_seen.set()
        if self.decoder_reset.is_set():
            return
        if self.wait_sps:
            joined = self.sps_tail + data
            position = first_sps(joined)
            if position is None:
                self.sps_tail = joined[-4:]
                return
            data = joined[position:]
            self.wait_sps = False
            self.sps_tail = b""
        if self.file:
            try:
                self.file.write(data)
            except OSError as error:
                                                                       
                                                                           
                                     
                self.last_file_error = str(error)
                try:
                    self.file.close()
                except OSError:
                    pass
                self.file = None
        if self.command:
            try:
                self.queue.put_nowait(data)
            except queue.Full:
                                                                             
                                                                               
                                             
                self.dropped += 1
                self.decoder_reset.set()
        self.preview.push(data)
        self.live.push(data)

    def reset_stream(self) -> None:
        """End the current HDMI stream before USB starts a new one."""
        self.data_seen.clear()
        self._clear_queue()
                                                                             
                                                                          
                                                        
        self.decoder_reset.set()
        self.preview.reset()
        self.live.reset()

    def status_snapshot(self) -> dict:
        with self.lock:
            process = self.process
        display = {}
        try:
            candidate = json.loads(Path("/run/goggles-lab/hdmi-status.json").read_text())
            if process is not None and candidate.get("pid") == process.pid and time.monotonic() - candidate.get("monotonic", 0) < 1.5:
                display = candidate
        except (OSError, ValueError, TypeError):
            pass
        rendered = bool(display.get("state") == "playing" and display.get("outputs") and all(item.get("rendered", 0) > 0 and item.get("age", 99) < 1 for item in display["outputs"]))
        return {
            "display_mode": display.get("mode", "unknown"),
            "display_rendering": rendered,
            "live_rendering": rendered and display.get("mode") == "live",
            "player_configured": bool(self.command),
            "fallback_configured": bool(self.fallback_command),
            "player_running": process is not None and process.poll() is None,
            "player_pid": process.pid if process is not None else None,
            "player_mode": display.get("mode", self.process_kind),
            "player_restarts": self.restarts,
            "player_dropped_chunks": self.dropped,
            "player_queue": self.queue.qsize(),
            "player_error": self.last_player_error,
            "file_error": self.last_file_error,
            "display_connected": self._display_connected(),
            "display_reset_pending": self.display_reset.is_set(),
            "output_profile": self.profile,
            "preview_available": bool(self.preview.path and self.preview.path.exists()),
            "preview_error": self.preview.last_error,
            **self.live.status(),
        }

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        if self.thread:
            self.thread.join(timeout=2)
        self._stop_process()
        self.preview.close()
        self.live.close()
        if self.file:
            try:
                self.file.flush()
                self.file.close()
            except OSError:
                pass


class AppDriver:
    """Replay the capture-derived arm once, then use the light sustain loop."""

    MAGIC_099_PAYLOAD = bytes.fromhex(
        "02020000d507000000000013000d0063616d6361705f636f6d6d6f6e00000000"
    )
    MAGIC_088_PAYLOAD = bytes.fromhex("1700002300415050000000000002")

    def __init__(self, session: "Session", sustain: bool = True,
                 logiclink_magic: bool = False):
        self.session = session
        self.sustain = sustain
        self.logiclink_magic = logiclink_magic
        self.seq = 0xD4E1
        self.magic_counter = 0

    def send_tuple(self, packet_tuple: tuple) -> bool:
        cmd_set, cmd_id, sender_type, sender_idx, receiver_type, receiver_idx, ack_type, payload_hex = packet_tuple
        self.seq = (self.seq + 1) & 0xFFFF
        packet = duml.build(
            sender_type, receiver_type, self.seq, cmd_set, cmd_id,
            bytes.fromhex(payload_hex), sender_idx=sender_idx,
            receiver_idx=receiver_idx, ack_type=ack_type,
        )
        return self.session.send_bulk_in(aoa.wrap(packet))

    def replay(self, sequence: list[tuple], gap_cap: float) -> None:
        previous = sequence[0][0] if sequence else 0.0
        for timestamp, packet_tuple in sequence:
            if STOP.is_set() or not self.session.configured:
                return
            time.sleep(min(max(0.0, timestamp - previous), gap_cap))
            previous = timestamp
            if not self.send_tuple(packet_tuple) and not self.session.configured:
                return

    def send_logiclink_magic(self) -> bool:
        """Send the newer LogicLink live-view start/keepalive pair."""
        payload_099 = bytearray(self.MAGIC_099_PAYLOAD)
        payload_099[4] = (0xD5 + self.magic_counter) & 0xFF
        packet_099 = duml.build(
            2, 8, 0xFEF3, 0, 0x99, bytes(payload_099),
            receiver_idx=1, ack_type=2,
        )
        packet_088 = duml.build(
            2, 28, 0xFEF4, 0, 0x88, self.MAGIC_088_PAYLOAD,
            receiver_idx=1, ack_type=2,
        )
        if not self.session.send_bulk_in(aoa.wrap(packet_099)):
            return False
        time.sleep(0.05)
        if not self.session.send_bulk_in(aoa.wrap(packet_088)):
            return False
        self.magic_counter += 1
        return True

    def run(self) -> None:
        from .gold_app_seq import APP_SEQ, SUSTAIN_SEQ
                                                                        
                                                                          
                                          
        time.sleep(0.12)
        if self.logiclink_magic:
                                                                          
                                                                             
                                                                             
                                                                      
            self.replay(APP_SEQ, gap_cap=0.08)
            if STOP.is_set() or not self.session.configured:
                return
            while not STOP.is_set() and self.session.configured:
                if not self.send_logiclink_magic():
                    return
                time.sleep(5.0)
            return
        self.replay(APP_SEQ, gap_cap=0.08)
        if not self.sustain:
            return
        while not STOP.is_set() and self.session.configured:
            self.replay(SUSTAIN_SEQ, gap_cap=0.5)


class Session:
    def __init__(self, gadget: RawGadget, output: VideoOutput, verbose: bool,
                 trace: TraceLogger | None = None, sustain: bool = True,
                 logiclink_magic: bool = False):
        self.gadget, self.output, self.verbose, self.trace = gadget, output, verbose, trace
        self.sustain = sustain
        self.logiclink_magic = logiclink_magic
        self.mode = "normal"
        self.configured = False
        self.pending_reenum = False
        self.ep_out = self.ep_in = None
        self.reader = self.driver = None
        self.deframer = VideoDeframer()
        self.control_buffer = bytearray()
        self.video_pending: list[bytes] = []
        self.video_started = False
        self.video_bytes = 0
        self.video_lock = threading.Lock()
        self.video_last_monotonic: float | None = None
        self.video_idle_stops = 0
        self.video_watchdog_stop = threading.Event()
        self.tx_lock = threading.Lock()
        self.control_seq_lock = threading.Lock()
        self.control_condition = threading.Condition()
        self.control_history: deque[dict] = deque(maxlen=256)
        self.control_seq = 0xE000
        self.video_watchdog = threading.Thread(
            target=self._video_watchdog_loop, name="video-watchdog", daemon=True
        )
        self.video_watchdog.start()

                                                                            
                                                                          
                                                                             
                                                                              
                                                               
    VIDEO_IDLE_TIMEOUT = 1.5
    VIDEO_WATCHDOG_INTERVAL = 0.05

    def _video_watchdog_loop(self) -> None:
        while not self.video_watchdog_stop.wait(self.VIDEO_WATCHDOG_INTERVAL):
            try:
                self._stop_stale_video()
            except Exception as error:
                                                                           
                if self.trace:
                    self.trace.error(f"video_watchdog {error}")

    def _stop_stale_video(self) -> bool:
        now = time.monotonic()
        with self.tx_lock:
            if not self.configured:
                return False
            with self.video_lock:
                last = self.video_last_monotonic
                active = self.video_started or bool(self.video_pending)
                if last is None or not active or now - last < self.VIDEO_IDLE_TIMEOUT:
                    return False
                self.video_started = False
                self.video_pending.clear()
                self.video_last_monotonic = None
                self.video_idle_stops += 1
                                                                        
                                                                         
                self.output.reset_stream()
        if self.trace:
            self.trace.event("video_idle", f"stopped_after={self.VIDEO_IDLE_TIMEOUT:.2f}s")
        return True

    @property
    def pid(self) -> int:
        return PID_ACCESSORY if self.mode == "accessory" else PID_NORMAL

    def log(self, text: str) -> None:
        if self.verbose:
            print(text, flush=True)

    def _next_control_seq(self) -> int:
        with self.control_seq_lock:
            self.control_seq = (self.control_seq + 1) & 0xFFFF
            return self.control_seq

    def _record_control_packet(self, direction: str, packet: bytes, note: str = "") -> dict | None:
        parsed = duml.parse(packet)
        if parsed is None:
            return None
        entry = {
            "time": time.time(),
            "direction": direction,
            "note": note,
            "packet_hex": packet.hex(),
            "version": parsed["version"],
            "seq": parsed["seq"],
            "packet_type": parsed["packet_type"],
            "ack_type": parsed["ack_type"],
            "sender_type": parsed["sender_type"],
            "sender_idx": parsed["sender_idx"],
            "receiver_type": parsed["receiver_type"],
            "receiver_idx": parsed["receiver_idx"],
            "cmd_set": parsed["cmd_set"],
            "cmd_id": parsed["cmd_id"],
            "payload_hex": parsed["payload"].hex(),
        }
        with self.control_condition:
            self.control_history.append(entry)
            self.control_condition.notify_all()
        if self.trace:
            self.trace.control_packet(direction, packet, note=note)
        return entry

    def _record_aoa_packet(self, direction: str, data: bytes, note: str = "") -> None:
        if not data.startswith(aoa.AOA_MAGIC) or len(data) < 8:
            return
        length = int.from_bytes(data[4:8], "little")
        if length < 13 or len(data) < 8 + length:
            return
        self._record_control_packet(direction, data[8:8 + length], note=note)

    def status_snapshot(self) -> dict:
        with self.control_condition:
            history = list(self.control_history)[-20:]
        with self.video_lock:
            video_started = self.video_started
            video_last = self.video_last_monotonic
            video_idle_stops = self.video_idle_stops
            video_pending_chunks = len(self.video_pending)
        video_age_ms = None
        if video_last is not None:
            video_age_ms = round(max(0.0, time.monotonic() - video_last) * 1000.0, 1)
        status = {
            "mode": self.mode,
            "configured": self.configured,
            "pid": f"0x{self.pid:04x}",
            "ep_out": self.ep_out,
            "ep_in": self.ep_in,
            "video_started": video_started,
            "video_bytes": self.video_bytes,
            "video_age_ms": video_age_ms,
            "video_idle_stops": video_idle_stops,
            "video_pending_chunks": video_pending_chunks,
            "control_packets": len(self.control_history),
            "recent_control": history,
        }
        status.update(self.output.status_snapshot())
        return status

    def handle_control(self, data: bytes) -> None:
        request = parse_control(data)
        if not request:
            return
        if self.trace:
            self.trace.ep0_request(request, data)
        request_type, code = request["type"], request["request"]
        value, index, length = request["value"], request["index"], request["length"]
        self.log(f"EP0 type=0x{request_type:02x} req=0x{code:02x} value=0x{value:04x} index={index} len={length}")
        if (request_type & USB_TYPE_MASK) == USB_TYPE_STANDARD:
            if code == USB_REQ_GET_DESCRIPTOR:
                dtype, string_index = value >> 8, value & 0xFF
                if dtype == USB_DT_DEVICE:
                    response = device_descriptor(self.pid)
                elif dtype in (USB_DT_CONFIG, USB_DT_OTHER_SPEED_CONFIG):
                    response = config_descriptor()
                elif dtype == USB_DT_STRING:
                    response = string_descriptor("", language=True) if string_index == 0 else string_descriptor(DESCRIPTOR_STRINGS.get(string_index, ""))
                elif dtype == USB_DT_DEVICE_QUALIFIER:
                    response = qualifier_descriptor()
                elif dtype == USB_DT_BOS:
                    self.gadget.ep0_stall()
                    return
                else:
                    self.gadget.ep0_stall()
                    return
                response = response[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note=f"descriptor=0x{dtype:02x}")
                return
            if code == USB_REQ_SET_CONFIGURATION:
                try:
                    self.gadget.ep0_read(0)
                except OSError:
                    pass
                self.set_configuration(value)
                return
            if code == USB_REQ_GET_CONFIGURATION:
                response = bytes([1 if self.configured else 0])[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note="get_configuration")
                return
            if code == USB_REQ_GET_INTERFACE:
                response = b"\x00"[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note="get_interface")
                return
            if code in (USB_REQ_SET_INTERFACE, USB_REQ_SET_ADDRESS):
                try:
                    self.gadget.ep0_read(0)
                except OSError:
                    pass
                return
            if code == USB_REQ_GET_STATUS:
                response = b"\x00\x00"[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note="get_status")
                return
        if (request_type & USB_TYPE_MASK) == USB_TYPE_VENDOR:
            if code == AOA_GET_PROTOCOL and request_type & USB_DIR_IN:
                response = AOA_PROTOCOL_VERSION.to_bytes(2, "little")[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note="AOA_GET_PROTOCOL")
                return
            if code == AOA_SEND_STRING and not request_type & USB_DIR_IN:
                text = self.gadget.ep0_read(length).rstrip(b"\x00").decode("utf-8", "replace")
                self.log(f"AOA string[{index}]={text!r}")
                if self.trace:
                    self.trace.event("aoa_string", f"index={index} text={text!r}")
                return
            if code == AOA_START and not request_type & USB_DIR_IN:
                self.gadget.ep0_read(0)
                self.pending_reenum = True
                if self.trace:
                    self.trace.event("aoa_start", "requested accessory re-enumeration")
                return
            if request_type & USB_DIR_IN:
                response = b"\x00\x00"[:length]
                self.gadget.ep0_write(response)
                if self.trace:
                    self.trace.ep0_response(length, response, note=f"vendor=0x{code:02x}")
            else:
                self.gadget.ep0_read(length)
            return
        self.gadget.ep0_stall()

    def set_configuration(self, value: int) -> None:
        if value == 0:
            self.reset(self.mode)
            return
        ep_out = ep_in = None
        try:
            with self.tx_lock:
                                                                           
                                                                       
                                                            
                if self.configured and self.ep_out is not None and self.ep_in is not None:
                    return
                self.configured = False
                self.ep_out = self.ep_in = None
            self.gadget.vbus_draw(500)
            self.gadget.configure()
            ep_out = self._enable_endpoint(0x01)
            ep_in = self._enable_endpoint(0x81)
        except OSError as error:
            with self.tx_lock:
                self.configured = False
                self.ep_out = self.ep_in = None
            self._disable_endpoints((ep_out, ep_in))
            self.log(f"USB configuration deferred: {error}")
            if self.trace:
                self.trace.event("configuration_error", str(error))
                                                                            
                                                                          
            return
        with self.tx_lock:
            self.ep_out, self.ep_in = ep_out, ep_in
            self.configured = True
        self.log(f"bulk endpoints enabled out={self.ep_out} in={self.ep_in} mode={self.mode}")
        if self.trace:
            self.trace.event("configured", f"value={value} mode={self.mode} pid=0x{self.pid:04x} "
                             f"ep_out={self.ep_out} ep_in={self.ep_in}")
        if self.mode == "accessory" and (self.reader is None or not self.reader.is_alive()):
            self.reader = threading.Thread(target=self.read_bulk, daemon=True)
            self.reader.start()
            self.driver = threading.Thread(
                target=AppDriver(
                    self,
                    sustain=self.sustain,
                    logiclink_magic=self.logiclink_magic,
                ).run,
                daemon=True,
            )
            self.driver.start()

    def _enable_endpoint(self, address: int) -> int:
        """Enable one endpoint, tolerating short dwc2/raw-gadget races."""
        last_error: OSError | None = None
        for attempt in range(8):
            try:
                return self.gadget.ep_enable(address)
            except OSError as error:
                last_error = error
                if error.errno == errno.EINVAL:
                                                                          
                                                               
                    return self.gadget.ep_enable(address, max_packet=64)
                if error.errno not in (errno.EAGAIN, errno.EBUSY, errno.EINTR):
                    raise
                time.sleep(0.05 * (attempt + 1))
        assert last_error is not None
        raise last_error

    def send_bulk_in(self, data: bytes) -> bool:
        self._record_aoa_packet("out", data)
        transport_lost: str | None = None
        with self.tx_lock:
            endpoint = self.ep_in
            if endpoint is None or not self.configured:
                return False
            if self.trace:
                self.trace.bulk_in(endpoint, data, note="queued")
            for attempt in range(4):
                try:
                    self.gadget.ep_write(endpoint, data)
                    return True
                except (TypeError, ValueError, OverflowError, struct.error):
                                                                             
                                                                        
                            
                    return False
                except OSError as error:
                    transient = error.errno in (
                        errno.EAGAIN, errno.EWOULDBLOCK, errno.EBUSY, errno.EINTR
                    )
                    if transient and attempt < 3:
                                                                            
                                                                            
                                                                              
                                                                          
                        time.sleep(0.005 * (attempt + 1))
                        continue
                    if error.errno in (
                        errno.EAGAIN, errno.EWOULDBLOCK, errno.EBUSY, errno.EINTR,
                        errno.ESHUTDOWN, errno.ENODEV, errno.EPIPE,
                    ):
                        if self.trace:
                            self.trace.event("bulk_in_stop", f"ep={endpoint} error={error}")
                        if self.ep_in == endpoint:
                            self.configured = False
                            transport_lost = str(error)
                    break
        if transport_lost is not None:
                                                                             
                                                                           
                                                                           
                                                                      
                                                                         
                                      
            self._transport_lost(transport_lost)
        return False

    def _transport_lost(self, reason: str) -> None:
        """Stop HDMI immediately when the UDC reports a broken transport."""
        with self.tx_lock:
            self.configured = False
            with self.video_lock:
                self.video_pending.clear()
                self.video_started = False
                self.video_last_monotonic = None
            self.output.reset_stream()
        if self.trace:
            self.trace.event("transport_lost", reason)

    def _disable_endpoints(self, endpoints: tuple[int | None, ...]) -> None:
        for endpoint in endpoints:
            if endpoint is None:
                continue
            try:
                self.gadget.ep_disable(endpoint)
            except OSError as error:
                                                                          
                                                                         
                                                                        
                if self.trace:
                    self.trace.event("endpoint_disable", f"ep={endpoint} error={error}")

    def send_camera_command(self, name: str, value=None, **kwargs) -> dict:
        info = camera_control.command_info(name)
        payload = kwargs.pop("payload", None)
        if payload is None:
            payload = camera_control.known_payload(name, value)
        return self.send_raw_command(info.cmd_set, info.cmd_id, payload,
                                     name=info.name, **kwargs)

    def send_raw_command(self, cmd_set: int, cmd_id: int, payload: bytes,
                         *, name: str = "raw", receiver_type: int = camera_control.CAMERA_TYPE,
                         receiver_idx: int = 0, ack_type: int = 2, wait_ms: int = 800) -> dict:
        if not self.configured or self.ep_in is None:
            raise RuntimeError("USB accessory session is not configured; connect the goggles first")
        if not 0 <= cmd_set <= 0xFF or not 0 <= cmd_id <= 0xFF:
            raise ValueError("cmd_set and cmd_id must be 0..255")
        if not 0 <= receiver_type <= 0x1F or not 0 <= receiver_idx <= 7:
            raise ValueError("receiver_type must be 0..31 and receiver_idx 0..7")
        if not 0 <= ack_type <= 3:
            raise ValueError("ack_type must be 0..3")
        if len(payload) > 0x3F0:
            raise ValueError("payload is too large for one DUML packet")
        seq = self._next_control_seq()
        packet = duml.build(
            sender_type=camera_control.APP_TYPE,
            receiver_type=receiver_type,
            seq=seq,
            cmd_set=cmd_set,
            cmd_id=cmd_id,
            payload=payload,
            receiver_idx=receiver_idx,
            ack_type=ack_type,
        )
        sent = self.send_bulk_in(aoa.wrap(packet))
        replies = []
        if sent and wait_ms > 0:
            deadline = time.monotonic() + min(wait_ms, 10000) / 1000.0
            with self.control_condition:
                while time.monotonic() < deadline:
                    replies = [
                        entry for entry in self.control_history
                        if entry["direction"] == "in"
                        and entry["seq"] == seq
                        and entry["cmd_set"] == cmd_set
                        and entry["cmd_id"] == cmd_id
                    ]
                    if replies:
                        break
                    self.control_condition.wait(timeout=max(0.0, deadline - time.monotonic()))
        result = {
            "name": name,
            "sent": sent,
            "seq": seq,
            "cmd_set": cmd_set,
            "cmd_id": cmd_id,
            "payload_hex": payload.hex(),
            "packet_hex": packet.hex(),
            "replies": replies,
        }
        self.log(f"camera command {name} set=0x{cmd_set:02x} id=0x{cmd_id:02x} "
                 f"payload={payload.hex()} sent={sent} replies={len(replies)}")
        return result

    def read_bulk(self) -> None:
        try:
            while not STOP.is_set():
                with self.tx_lock:
                    configured = self.configured
                    endpoint = self.ep_out
                if not configured or endpoint is None:
                    return
                try:
                    data = self.gadget.ep_read(endpoint)
                except OSError as error:
                                                                            
                                                                          
                                                                         
                    if self.trace:
                        self.trace.event("bulk_reader_stop", str(error))
                    return
                if not data:
                    time.sleep(0.002)
                    continue
                if self.trace:
                    self.trace.bulk_out(endpoint, data)
                for payload in self.deframer.feed(data):
                    self.handle_video(payload)
                if aoa.AOA_MAGIC in data:
                    self.control_buffer.extend(data)
                    for packet in aoa.unwrap(self.control_buffer):
                        self._record_control_packet("in", packet)
                        reply = aoa.identity_reply(packet)
                        if reply:
                            self.send_bulk_in(aoa.wrap(reply))
        finally:
            if self.reader is threading.current_thread():
                self.reader = None

    def handle_video(self, payload: bytes) -> None:
        if self.trace:
            self.trace.video(payload, self.deframer.stats())
                                                                            
                                                                            
                                                                   
        with self.tx_lock:
            if not self.configured:
                return
            if self.output.consume_display_reset():
                with self.video_lock:
                    self.video_pending.clear()
                    self.video_started = False
                    self.video_last_monotonic = None
            with self.video_lock:
                self.video_last_monotonic = time.monotonic()
                if self.video_started:
                    data = payload
                else:
                    self.video_pending.append(payload)
                    joined = b"".join(self.video_pending)
                    position = first_sps(joined)
                    if position is None:
                        return
                    data = joined[position:]
                    self.video_pending.clear()
                    self.video_started = True
                self.video_bytes += len(data)
            self.output.push(data)

    def reset(self, mode: str) -> None:
        if self.trace:
            self.trace.event("reset", f"new_mode={mode}")
        with self.tx_lock:
            self.configured = False
            endpoints = tuple(endpoint for endpoint in (self.ep_out, self.ep_in)
                              if endpoint is not None)
            self.ep_out = self.ep_in = None
            with self.video_lock:
                self.video_pending.clear()
                self.video_started = False
                self.video_last_monotonic = None
                                                                        
                                                                            
                                                         
            self.output.reset_stream()
        self.mode = mode
        self.pending_reenum = False
        current = threading.current_thread()
        for worker in (self.reader, self.driver):
            if worker is not None and worker is not current:
                                                                           
                                                                          
                                                                        
                worker.join(timeout=2.0)
        if self.reader is not None and not self.reader.is_alive():
            self.reader = None
        if self.driver is not None and not self.driver.is_alive():
            self.driver = None
        self._disable_endpoints(endpoints)
        self.deframer = VideoDeframer()
        self.control_buffer.clear()

    def close(self) -> None:
        self.video_watchdog_stop.set()
        if self.video_watchdog is not threading.current_thread():
            self.video_watchdog.join(timeout=0.5)
        with self.tx_lock:
            self.configured = False
            endpoints = tuple(endpoint for endpoint in (self.ep_out, self.ep_in)
                              if endpoint is not None)
            self.ep_out = self.ep_in = None
            with self.video_lock:
                self.video_pending.clear()
                self.video_started = False
                self.video_last_monotonic = None
        current = threading.current_thread()
        for worker in (self.reader, self.driver):
            if worker is not None and worker is not current:
                worker.join(timeout=2.0)
        self._disable_endpoints(endpoints)
        self.output.close()


def offline(args: argparse.Namespace) -> int:
    output = VideoOutput(args.out, args.player_cmd, args.display_status, args.settings_file, fallback_video=args.fallback_video)
    deframer = VideoDeframer()
    source = open(args.input, "rb") if args.input else sys.stdin.buffer
    pending: list[bytes] = []
    started = False
    try:
        while True:
            data = source.read(65536)
            if not data:
                break
            for payload in deframer.feed(data):
                if started:
                    output.push(payload)
                    continue
                pending.append(payload)
                joined = b"".join(pending)
                position = first_sps(joined)
                if position is not None:
                    output.push(joined[position:])
                    started = True
                    pending.clear()
    finally:
        if args.input:
            source.close()
        output.close()
    print(f"offline video chunks={deframer.chunks} bytes={deframer.bytes} resyncs={deframer.resyncs}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--driver", default="fe980000.usb")
    parser.add_argument("--device", default="fe980000.usb")
    parser.add_argument("--out", default="/tmp/dji-pi.h264")
    parser.add_argument("--player-cmd", help="command that reads Annex-B H.264 from stdin")
    parser.add_argument("--display-status", help="DRM connector status sysfs path")
    parser.add_argument("--settings-file", default=DEFAULT_SETTINGS_PATH,
                        help=f"JSON output profile read before each HDMI player start (default: {DEFAULT_SETTINGS_PATH})")
    parser.add_argument("--preview-path", help="write a bounded low-resolution JPEG preview for the dashboard")
    parser.add_argument("--live-socket", default="/run/goggles-lab/live.mp4",
                        help="Unix socket with live fMP4 for the dashboard browser view")
    parser.add_argument("--fallback-video", help="loop this MP4 on HDMI while no live H.264 signal is present")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--input", help="framed video input for --offline; default stdin")
    parser.add_argument("--log-dir", help="write detailed session logs to this directory")
    parser.add_argument("--capture-raw", action="store_true",
                        help="also save incoming bulk bytes, bounded by --raw-limit-mb")
    parser.add_argument("--raw-limit-mb", type=int, default=32,
                        help="maximum raw bulk capture size (default: 32 MiB)")
    parser.add_argument("--video-log-every", type=int, default=1,
                        help="write every Nth video chunk to video.log (default: 1)")
    parser.add_argument("--log-limit-mb", type=int, default=32,
                        help="rotate each text log at this size; 0 disables rotation")
    parser.add_argument("--control-socket", default=DEFAULT_SOCKET,
                        help=f"Unix-socket camera API (default: {DEFAULT_SOCKET})")
    parser.add_argument("--reenum-settle", type=float, default=0.12,
                        help="seconds to wait before reopening raw-gadget after AOA start")
    parser.add_argument("--no-sustain", action="store_true",
                        help="diagnostic: send the capture-derived arm once without the sustain loop")
    parser.add_argument("--logiclink-magic", action="store_true",
                        help="use the newer LogicLink 0x99/0x88 live-view start/keepalive pair")
    parser.add_argument("--no-control-api", action="store_true",
                        help="disable the local camera-control API")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    if args.offline:
        return offline(args)
    if os.geteuid() != 0:
        parser.error("the raw-gadget endpoint requires root; use sudo")
    trace = None
    if args.log_dir:
        trace = TraceLogger(
            args.log_dir,
            capture_raw=args.capture_raw,
            raw_limit_mb=args.raw_limit_mb,
            video_every=args.video_log_every,
            log_limit_mb=args.log_limit_mb,
        )
        trace.event("startup", f"driver={args.driver} device={args.device} out={args.out!r} "
                               f"player={args.player_cmd!r}")
    gadget = None
    retry_notice = 0.0
    while gadget is None:
        try:
            gadget = RawGadget(args.driver, args.device)
        except OSError as error:
            now = time.monotonic()
            if now >= retry_notice:
                print(f"[!] raw-gadget is not ready ({error}); retrying", flush=True)
                if trace:
                    trace.event("raw_gadget_retry", str(error))
                retry_notice = now + 5.0
            time.sleep(0.5)
    session = Session(
        gadget,
        VideoOutput(args.out, args.player_cmd, args.display_status, args.settings_file, args.preview_path, args.fallback_video, args.live_socket or None),
        args.verbose,
        trace=trace,
        sustain=not args.no_sustain,
        logiclink_magic=args.logiclink_magic,
    )
    control_api = None
    if not args.no_control_api:
        control_api = ControlServer(session, args.control_socket)
        control_api.start()
        if trace:
            trace.event("control_api", f"socket={args.control_socket}")
    def stop(_signum, _frame):
        STOP.set()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    print("[*] goggles USB-host <-> Pi USB-gadget; waiting for AOA handshake", flush=True)
    try:
        while not STOP.is_set():
            try:
                event, data = gadget.event_fetch()
            except OSError as error:
                if STOP.is_set() and error.errno in (errno.EINTR, errno.EBADF):
                    break
                raise
            if event == USB_RAW_EVENT_CONNECT:
                print(f"[*] USB CONNECT mode={session.mode}", flush=True)
                if trace:
                    trace.event("usb_connect", f"mode={session.mode} pid=0x{session.pid:04x}")
            elif event == USB_RAW_EVENT_CONTROL:
                try:
                    session.handle_control(data)
                except OSError as error:
                    if STOP.is_set() and error.errno in (errno.EINTR, errno.EPIPE, errno.ENODEV):
                        break
                    raise
                if session.pending_reenum:
                    print("[*] AOA START -> re-enumerate as 18d1:2d01", flush=True)
                    if trace:
                        trace.event("reenumerate", "normal->accessory pid=0x2d01")
                    session.reset("accessory")
                    gadget.reinit(settle=max(0.05, args.reenum_settle))
            elif event == USB_RAW_EVENT_RESET:
                session.reset(session.mode)
                if trace:
                    trace.event("usb_reset", "configuration cleared")
            elif event == USB_RAW_EVENT_DISCONNECT:
                if trace:
                    trace.event("usb_disconnect", "waiting for host reconnect")
                session.reset("normal")
    finally:
        if control_api:
            control_api.close()
        session.close()
                                                                       
                                                                     
                                                                        
                                                                        
                                                                        
        if session.reader is None or not session.reader.is_alive():
            gadget.close()
        elif trace:
            trace.event("shutdown", "reader still active; deferred raw-gadget close to process teardown")
        if trace:
            trace.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
