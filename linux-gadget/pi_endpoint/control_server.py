"""Small local control API for the Pi-side DJI camera session.

The receiver is intentionally usable without a web framework.  A Unix
domain socket carries one JSON object per line and returns one JSON object per
line.  This keeps the protocol easy to drive from a shell, a future HDMI UI,
or a network service while keeping the USB/DUML state machine in one place.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Any

from . import camera_control

DEFAULT_SOCKET = "/tmp/dji-pi-control.sock"
MAX_LINE = 1024 * 1024


class ControlServer:
    def __init__(self, session: Any, socket_path: str = DEFAULT_SOCKET):
        self.session = session
        self.socket_path = Path(socket_path).expanduser()
        self._listener: socket.socket | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._bound = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o660)
                                                                          
                                                               
        sudo_uid = os.environ.get("SUDO_UID")
        sudo_gid = os.environ.get("SUDO_GID")
        if sudo_uid and sudo_gid and os.geteuid() == 0:
            os.chown(self.socket_path, int(sudo_uid), int(sudo_gid))
        listener.listen(8)
        listener.settimeout(0.25)
        self._listener = listener
        self._bound = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, name="dji-control", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._listener.accept() if self._listener else (None, None)
            except socket.timeout:
                continue
            except OSError:
                return
            if connection is None:
                continue
            threading.Thread(target=self._client, args=(connection,), daemon=True).start()

    def _client(self, connection: socket.socket) -> None:
        with connection:
            connection.settimeout(5.0)
            buffer = bytearray()
            while not self._stop.is_set():
                try:
                    chunk = connection.recv(65536)
                except (OSError, socket.timeout):
                    return
                if not chunk:
                    return
                buffer.extend(chunk)
                if len(buffer) > MAX_LINE:
                    self._write(connection, {"ok": False, "error": "request too large"})
                    return
                while b"\n" in buffer:
                    raw, _, remainder = buffer.partition(b"\n")
                    buffer = bytearray(remainder)
                    if not raw.strip():
                        continue
                    try:
                        request = json.loads(raw.decode("utf-8"))
                        response = self.dispatch(request)
                    except Exception as error:                                                   
                        response = {"ok": False, "error": str(error), "error_type": type(error).__name__}
                    self._write(connection, response)

    @staticmethod
    def _write(connection: socket.socket, response: dict) -> None:
        data = (json.dumps(response, separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")
        try:
            connection.sendall(data)
        except OSError:
            pass

    def dispatch(self, request: dict) -> dict:
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object")
        operation = str(request.get("op", request.get("command", ""))).lower()
        if operation == "status":
            return {"ok": True, "status": self.session.status_snapshot()}
        if operation in ("output_reload", "reload_output", "apply_output"):
            return {"ok": True, "result": self.session.output.reload_profile()}
        if operation in ("list", "list_commands", "commands"):
            return {"ok": True, "commands": camera_control.list_commands()}
        if operation == "record":
            state = request.get("state", request.get("value"))
            return {"ok": True, "result": self.session.send_camera_command(
                "record", state, wait_ms=int(request.get("wait_ms", 800)))}
        if operation in ("photo", "take_photo"):
            return {"ok": True, "result": self.session.send_camera_command(
                "photo", wait_ms=int(request.get("wait_ms", 800)))}
        if operation in ("mode", "working_mode"):
            value = request.get("mode", request.get("value"))
            return {"ok": True, "result": self.session.send_camera_command(
                "mode", value, wait_ms=int(request.get("wait_ms", 800)))}
        if operation in ("set", "camera"):
                                                                            
                                                                               
            action = str(request.get("action", ""))
            if action in ("record_start", "record_stop"):
                value = "start" if action.endswith("start") else "stop"
                return {"ok": True, "result": self.session.send_camera_command(
                    "record", value, wait_ms=int(request.get("wait_ms", 800)))}
            if action in ("photo", "take_photo"):
                return {"ok": True, "result": self.session.send_camera_command(
                    "photo", wait_ms=int(request.get("wait_ms", 800)))}
            if action in ("mode", "working_mode"):
                return {"ok": True, "result": self.session.send_camera_command(
                    "mode", request.get("value"), wait_ms=int(request.get("wait_ms", 800)))}
            return self._send_named(request)
        if operation in ("send", "command", "raw"):
            return self._send_named(request)
        raise ValueError("op must be status, list, record, photo, mode, set, or command")

    def _send_named(self, request: dict) -> dict:
        name = request.get("name")
        cmd_set = request.get("cmd_set")
        cmd_id = request.get("cmd_id")
        payload_hex = request.get("payload_hex")
        if name is not None:
            info = camera_control.command_info(str(name))
            if info.destructive and not request.get("allow_destructive", False):
                raise ValueError(f"{info.name} is destructive; set allow_destructive=true explicitly")
            if payload_hex is None:
                payload = camera_control.known_payload(str(name), request.get("value"))
            else:
                payload = bytes.fromhex(str(payload_hex))
            return {
                "ok": True,
                "result": self.session.send_raw_command(
                    info.cmd_set,
                    info.cmd_id,
                    payload,
                    name=info.name,
                    receiver_type=int(request.get("receiver_type", camera_control.CAMERA_TYPE)),
                    receiver_idx=int(request.get("receiver_idx", 0)),
                    ack_type=int(request.get("ack_type", 2)),
                    wait_ms=int(request.get("wait_ms", 800)),
                ),
            }
        if cmd_set is None or cmd_id is None:
            raise ValueError("command requires name or cmd_set and cmd_id")
        if (int(cmd_set), int(cmd_id)) in ((0x02, 0x72), (0x02, 0x79))\
                and not request.get("allow_destructive", False):
            raise ValueError("destructive camera command; set allow_destructive=true explicitly")
        if payload_hex is None:
            raise ValueError("command requires payload_hex")
        return {
            "ok": True,
            "result": self.session.send_raw_command(
                int(cmd_set),
                int(cmd_id),
                bytes.fromhex(str(payload_hex)),
                name="raw",
                receiver_type=int(request.get("receiver_type", camera_control.CAMERA_TYPE)),
                receiver_idx=int(request.get("receiver_idx", 0)),
                ack_type=int(request.get("ack_type", 2)),
                wait_ms=int(request.get("wait_ms", 800)),
            ),
        }

    def close(self) -> None:
        self._stop.set()
        listener, self._listener = self._listener, None
        if listener is not None:
            try:
                listener.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1)
        if self._bound:
            try:
                self.socket_path.unlink()
            except FileNotFoundError:
                pass
            self._bound = False
