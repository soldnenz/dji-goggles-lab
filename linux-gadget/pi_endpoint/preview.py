"""Small, bounded JPEG preview generated from the incoming H.264 stream."""
from __future__ import annotations

from pathlib import Path
import os
import queue
import subprocess
import threading
import time


class PreviewEncoder:
    """Best-effort low-resolution preview; never blocks USB or HDMI."""

    def __init__(self, path: str | None, width: int = 320, height: int = 180,
                 fps: int = 2):
        self.path = Path(path) if path else None
        self.width = width
        self.height = height
        self.fps = fps
        self.queue: queue.Queue[bytes | None] = queue.Queue(maxsize=6)
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.process: subprocess.Popen | None = None
        self.last_error = ""
        self.writer: threading.Thread | None = None
        self.reader: threading.Thread | None = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.writer = threading.Thread(target=self._write_loop, name="video-preview-in", daemon=True)
            self.reader = threading.Thread(target=self._read_loop, name="video-preview-out", daemon=True)
            self.writer.start()
            self.reader.start()

    def _command(self) -> list[str]:
        caps = f"video/x-raw,width={self.width},height={self.height},framerate={self.fps}/1"
        return [
            "gst-launch-1.0", "-q", "fdsrc", "fd=0", "do-timestamp=true", "!",
            "h264parse", "!", "avdec_h264", "!", "videoconvert", "!", "videoscale",
            "!", "videorate", "!", caps, "!", "jpegenc", "quality=55", "!",
            "fdsink", "fd=1",
        ]

    def _ensure_process(self) -> subprocess.Popen | None:
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.process
            try:
                process = subprocess.Popen(
                    self._command(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
            except OSError as error:
                self.last_error = str(error)
                return None
            self.process = process
            return process

    def push(self, data: bytes) -> None:
        if not self.path or self.stop_event.is_set():
            return
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(data)
            except queue.Empty:
                pass

    def _write_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                data = self.queue.get(timeout=0.1)
            except queue.Empty:
                continue
            if data is None:
                break
            process = self._ensure_process()
            if process is None or process.stdin is None:
                continue
            try:
                process.stdin.write(data)
                process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as error:
                self.last_error = str(error)
                with self.lock:
                    if self.process is process:
                        self.process = None
                try:
                    process.kill()
                except OSError:
                    pass

    def _publish(self, frame: bytes) -> None:
        if not self.path or len(frame) < 4:
            return
        temporary = self.path.with_suffix(".tmp")
        try:
            temporary.write_bytes(frame)
            os.replace(temporary, self.path)
        except OSError as error:
            self.last_error = str(error)
            try:
                temporary.unlink()
            except OSError:
                pass

    def _read_loop(self) -> None:
        buffer = bytearray()
        while not self.stop_event.is_set():
            process = self._ensure_process()
            if process is None or process.stdout is None:
                time.sleep(0.25)
                continue
            try:
                data = process.stdout.read(65536)
            except (OSError, ValueError) as error:
                self.last_error = str(error)
                data = b""
            if not data:
                if process.poll() is not None:
                    with self.lock:
                        if self.process is process:
                            self.process = None
                time.sleep(0.05)
                continue
            buffer.extend(data)
            while True:
                start = buffer.find(b"\xff\xd8")
                if start < 0:
                    if len(buffer) > 2:
                        del buffer[:-2]
                    break
                end = buffer.find(b"\xff\xd9", start + 2)
                if end < 0:
                    if start:
                        del buffer[:start]
                    break
                frame = bytes(buffer[start:end + 2])
                del buffer[:end + 2]
                self._publish(frame)

    def reset(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        if self.path:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass

    def close(self) -> None:
        self.stop_event.set()
        try:
            self.queue.put_nowait(None)
        except queue.Full:
            pass
        with self.lock:
            process, self.process = self.process, None
        if process is not None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except (OSError, ValueError):
                pass
            try:
                process.terminate()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        for thread in (self.writer, self.reader):
            if thread:
                thread.join(timeout=1)
        self.reset()
