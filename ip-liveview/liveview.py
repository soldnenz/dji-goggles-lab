#!/usr/bin/env python3
"""Liveview: PyAV decode + native Mac video window + Tk telemetry.

DJI liveview is High-profile P-slices with almost no IDR. VideoToolbox fails.
Piping Annex-B into ffplay also fails for live: it buffers seconds and any
dropped AU shreds every following P-frame.

Decode here with libavcodec FLAG2_SHOW_ALL (same path that looked acceptable),
never drop H.264, and only blit the latest YUV into ffplay as rawvideo — a
Cocoa/SDL window without an H.264 demuxer.
"""
from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Any

import av
import av.error
import numpy as np

from features import BUILD_MARK
from receiver import Session, add_common_args

AV_CODEC_FLAG2_SHOW_ALL = 1 << 22
AV_CODEC_FLAG_LOW_DELAY = 1 << 19


def _ffplay_bin() -> str | None:
    for cand in (shutil.which("ffplay"), "/opt/homebrew/bin/ffplay", "/usr/local/bin/ffplay"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def parameter_sets(annexb: bytes) -> bytes:
    """Keep the latest SPS (NAL 7) + PPS (NAL 8). Used if a decoder restart needs them."""
    sps = pps = b""
    i = 0
    n = len(annexb)
    while i + 4 < n:
        if annexb[i : i + 4] == b"\x00\x00\x00\x01":
            sc = 4
        elif annexb[i : i + 3] == b"\x00\x00\x01":
            sc = 3
        else:
            i += 1
            continue
        k = i + sc
        while k + 3 <= n:
            if annexb[k : k + 4] == b"\x00\x00\x00\x01" or annexb[k : k + 3] == b"\x00\x00\x01":
                break
            k += 1
        else:
            k = n
        nal = annexb[i:k]
        if len(nal) > sc:
            ntype = nal[sc] & 0x1F
            if ntype == 7:
                sps = nal
            elif ntype == 8:
                pps = nal
        i = k
    return sps + pps


class H264Decoder:
    def __init__(self) -> None:
        self._ctx = self._new()

    def _new(self) -> av.CodecContext:
        ctx = av.CodecContext.create("h264", "r")
        ctx.flags |= AV_CODEC_FLAG_LOW_DELAY
        ctx.flags2 |= AV_CODEC_FLAG2_SHOW_ALL
        try:
            ctx.thread_count = 1
        except Exception:
            pass
        try:
            ctx.open()
        except av.error.FFmpegError:
            pass
        return ctx

    def reset(self) -> None:
        self._ctx = self._new()

    def push(self, annexb: bytes) -> list[tuple[int, int, bytes]]:
        if not annexb:
            return []
        try:
            packets = list(self._ctx.parse(annexb) or [])
        except av.error.FFmpegError:
            return []
        out: list[tuple[int, int, bytes]] = []
        for packet in packets:
            try:
                frames = self._ctx.decode(packet)
            except av.error.FFmpegError:
                continue
            for frame in frames:
                yuv = np.ascontiguousarray(frame.to_ndarray(format="yuv420p"))
                out.append((frame.width, frame.height, yuv.tobytes()))
        return out


def _ffmpeg_bin() -> str | None:
    for cand in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def display_filters(width: int, height: int, lut: str, intensity: float, expand_43: bool) -> list[str]:
    filters: list[str] = []
    if expand_43 and height > 0 and width / height < 1.5:
        filters.append("scale=1920:1080:force_original_aspect_ratio=decrease")
        filters.append("pad=1920:1080:(ow-iw)/2:(oh-ih)/2")
    if lut:
        path = lut.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
        strength = max(0.0, min(1.0, intensity))
        filters.append("format=gbrp")
        filters.append(f"lut3d=file='{path}':interp=tetrahedral:amount={strength:.3f}")
        filters.append("format=yuv420p")
    return filters


class NativeYuvPlayer:
    """ffplay raw YUV → native Cocoa/SDL window. No H.264 demux, no GOP buffer."""

    def __init__(self, lut: str = "", lut_intensity: float = 1.0, expand_43: bool = False) -> None:
        self.bin = _ffplay_bin()
        self.proc: subprocess.Popen[bytes] | None = None
        self.size: tuple[int, int] | None = None
        self.started = False
        self.lut = lut
        self.lut_intensity = lut_intensity
        self.expand_43 = expand_43

    def _ensure(self, width: int, height: int) -> str | None:
        if self.proc is not None and self.proc.poll() is None and self.size == (width, height):
            return None
        if not self.bin:
            return "ffplay не найден — brew install ffmpeg"
        self.stop()
        env = os.environ.copy()
        env.setdefault("SDL_HINT_VIDEO_HIGHDPI", "1")
        cmd = [
            self.bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostats",
            "-window_title",
            f"G3 liveview {BUILD_MARK}",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-framedrop",
            "-sync",
            "ext",
            "-an",
            "-f",
            "rawvideo",
            "-pixel_format",
            "yuv420p",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            "60",
            "-i",
            "pipe:0",
        ]
        vf = display_filters(width, height, self.lut, self.lut_intensity, self.expand_43)
        if vf:
            cmd.extend(["-vf", ",".join(vf)])
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
            bufsize=0,
        )
        self.size = (width, height)
        self.started = True
        return None

    def write(self, width: int, height: int, i420: bytes) -> str | None:
        err = self._ensure(width, height)
        if err:
            return err
        proc = self.proc
        if proc is None or proc.stdin is None or proc.poll() is not None:
            return "окно видео закрылось"
        try:
            proc.stdin.write(i420)
        except (BrokenPipeError, OSError):
            self.stop()
            return "окно видео закрылось"
        return None

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        self.size = None
        self.started = False
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass


class MpegTsPublisher:
    """Annex-B → MPEG-TS/UDP for a local player or restreamer."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.bin = _ffmpeg_bin()
        self.proc: subprocess.Popen[bytes] | None = None

    def start(self) -> str:
        if not self.bin:
            return "ffmpeg не найден — RTSP/TS выключен"
        if self.proc is not None and self.proc.poll() is None:
            return f"mpegts udp://127.0.0.1:{self.port}"
        self.proc = subprocess.Popen(
            [
                self.bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-fflags",
                "nobuffer",
                "-f",
                "h264",
                "-i",
                "pipe:0",
                "-c",
                "copy",
                "-f",
                "mpegts",
                f"udp://127.0.0.1:{self.port}?pkt_size=1316",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        return f"mpegts udp://127.0.0.1:{self.port}"

    def write(self, annexb: bytes) -> None:
        proc = self.proc
        if not annexb or proc is None or proc.stdin is None or proc.poll() is not None:
            return
        try:
            proc.stdin.write(annexb)
        except (BrokenPipeError, OSError):
            self.stop()

    def stop(self) -> None:
        proc = self.proc
        self.proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except Exception:
            try:
                proc.kill()
            except OSError:
                pass


class LiveApp:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.events: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=256)
        self.h264_q: queue.Queue[bytes] = queue.Queue(maxsize=256)
        self.yuv_q: queue.Queue[tuple[int, int, bytes]] = queue.Queue(maxsize=1)
        self.decoder = H264Decoder()
        self._dec_lock = threading.Lock()
        self.player = NativeYuvPlayer(
            lut=getattr(args, "lut", "") or "",
            lut_intensity=float(getattr(args, "lut_intensity", 1.0)),
            expand_43=bool(getattr(args, "expand_43", False)),
        )
        self.publisher: MpegTsPublisher | None = None
        self.publish_detail = "off"
        rtsp_port = int(getattr(args, "rtsp_port", 0) or 0)
        if rtsp_port:
            self.publisher = MpegTsPublisher(rtsp_port)
            self.publish_detail = self.publisher.start()
        self.phase = "idle"
        self.detail = "нет линка"
        self.last_video = 0.0
        self.player_err = "" if self.player.bin else "ffplay не найден — brew install ffmpeg"
        self.stats = {"fps": 0.0, "kbps": 0.0, "frames": 0, "rtx": 0, "boost_via": "off"}
        self.last_log = ""
        self.stop = threading.Event()

        self.root = tk.Tk()
        self.root.title(f"G3 liveview {BUILD_MARK}")
        self.root.geometry("720x260+40+40")
        self.root.configure(bg="#101014")
        self.internal = tk.Label(
            self.root,
            text=BUILD_MARK,
            fg="#101014",
            bg="#d8c45a",
            font=("Helvetica", 12, "bold"),
            pady=4,
        )
        self.internal.pack(fill=tk.X)
        self.banner = tk.Label(
            self.root,
            text="НЕТ ВИДЕО",
            fg="#e64646",
            bg="#101014",
            font=("Helvetica", 22, "bold"),
            pady=12,
        )
        self.banner.pack(fill=tk.X)
        self.status = tk.Label(
            self.root,
            text="видео: PyAV → нативное окно\nждём линк",
            fg="#a0a0a8",
            bg="#101014",
            font=("Menlo", 13),
            justify=tk.LEFT,
            anchor="w",
            padx=16,
        )
        self.status.pack(fill=tk.BOTH, expand=True)

        self.tele = tk.Toplevel(self.root)
        self.tele.title("G3 telemetry")
        self.tele.geometry("720x840+780+40")
        self.tele.configure(bg="#101014")
        mono = tkfont.Font(family="Menlo", size=12)
        self.tele_text = tk.Text(
            self.tele,
            bg="#101014",
            fg="#d8d8d8",
            insertbackground="#d8d8d8",
            font=mono,
            wrap=tk.NONE,
            state=tk.DISABLED,
        )
        scroll = tk.Scrollbar(self.tele, command=self.tele_text.yview)
        self.tele_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tele_text.pack(fill=tk.BOTH, expand=True)
        self._show_idle("нет линка")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.tele.protocol("WM_DELETE_WINDOW", self.close)

    def close(self) -> None:
        self.stop.set()
        self.player.stop()
        if self.publisher is not None:
            self.publisher.stop()
        self.root.destroy()

    def emit(self, event: dict[str, Any]) -> None:
        if event.get("kind") == "frame":
            blob = event.get("h264") or b""
            if self.publisher is not None:
                self.publisher.write(blob)
            try:
                self.h264_q.put_nowait(blob)
            except queue.Full:
                # Never drop an already-queued AU (that shreds the GOP). Skip this one.
                pass
            return
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass

    def engine_loop(self) -> None:
        Session(self.args, self.emit).run()

    def decoder_loop(self) -> None:
        while not self.stop.is_set():
            try:
                blob = self.h264_q.get(timeout=0.1)
            except queue.Empty:
                continue
            pending = [blob]
            while True:
                try:
                    pending.append(self.h264_q.get_nowait())
                except queue.Empty:
                    break
            try:
                frames: list[tuple[int, int, bytes]] = []
                with self._dec_lock:
                    for item in pending:
                        frames.extend(self.decoder.push(item))
            except Exception:
                with self._dec_lock:
                    self.decoder.reset()
                continue
            if not frames:
                continue
            latest = frames[-1]
            try:
                self.yuv_q.put_nowait(latest)
            except queue.Full:
                try:
                    self.yuv_q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self.yuv_q.put_nowait(latest)
                except queue.Full:
                    pass

    def player_loop(self) -> None:
        while not self.stop.is_set():
            try:
                width, height, i420 = self.yuv_q.get(timeout=0.1)
            except queue.Empty:
                continue
            err = self.player.write(width, height, i420)
            if err:
                self.player_err = err
            else:
                self.player_err = ""
                self.last_video = time.monotonic()

    def _show_idle(self, sub: str) -> None:
        self.player.stop()
        with self._dec_lock:
            self.decoder.reset()
        self.banner.configure(text="НЕТ ВИДЕО", fg="#e64646")
        extra = f"\n{self.player_err}" if self.player_err else ""
        self.status.configure(text=f"{sub}\nкартинка в отдельном нативном окне{extra}")

    def _show_live(self) -> None:
        s = self.stats
        self.banner.configure(text="LIVE", fg="#7dcc7d")
        extra = f"\n{self.player_err}" if self.player_err else "\nокно ffplay = видео"
        self.status.configure(
            text=(
                f"{s['fps']:.0f} fps   {s['kbps'] / 1000:.1f} Mbps   "
                f"frames={s['frames']}   rtx={s['rtx']}"
                f"{extra}"
            )
        )

    def _tele_set(self, body: str) -> None:
        self.tele_text.configure(state=tk.NORMAL)
        self.tele_text.delete("1.0", tk.END)
        self.tele_text.insert(tk.END, body)
        self.tele_text.configure(state=tk.DISABLED)

    def _render_telemetry(self, event: dict[str, Any] | None = None) -> None:
        s = self.stats
        lines = [
            f"phase     {self.phase}",
            f"detail    {self.detail}",
            f"player    {self.player_err or ('ffplay yuv' if self.player.started else 'idle')}",
            f"build     {BUILD_MARK}",
            f"boost     {bool(self.args.boost)} {self.args.boost_kbps} kbps via {s.get('boost_via', 'off')}",
            f"usb       {self.last_log}",
            f"rtx       {bool(self.args.rtx)}",
            f"lut       {self.args.lut or 'off'}  intensity={self.args.lut_intensity}",
            f"expand43  {bool(self.args.expand_43)}",
            f"publish   {self.publish_detail}",
            f"fps       {s['fps']:.1f}",
            f"bitrate   {s['kbps'] / 1000:.2f} Mbps",
            f"frames    {s['frames']}",
            f"rtx req   {s['rtx']}",
            "",
        ]
        if event:
            lines += [
                f"peer      {event.get('peer', '')}",
                f"link      {event.get('name', '')}",
                f"session   0x{event.get('session', 0):04x}",
                f"t1 seq    {event.get('seq', '')}",
                f"t1 len    {event.get('length', '')}",
                f"win type2 {event.get('win2', '')}",
                f"win type3 {event.get('win3', '')}",
                f"win type5 {event.get('win5', '')}",
                f"serial    {event.get('serial', '')}",
                "",
                "DUML / type-1 payload:",
            ]
            duml = event.get("duml") or []
            if duml:
                lines.extend(f"  {row}" for row in duml)
            else:
                tail = event.get("raw_tail") or ""
                lines.append(f"  (empty) tail={tail}")
        else:
            lines.append("ещё нет type-1 пакетов")
        self._tele_set("\n".join(lines) + "\n")

    def pump(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event.get("kind")
                if kind == "status":
                    self.phase = event.get("phase", self.phase)
                    self.detail = event.get("detail", self.detail)
                    if self.phase == "live":
                        self._show_live()
                    else:
                        self._show_idle(self.detail)
                    self._render_telemetry()
                elif kind == "stats":
                    self.stats = {
                        "fps": event.get("fps", 0.0),
                        "kbps": event.get("kbps", 0.0),
                        "frames": event.get("frames", 0),
                        "rtx": event.get("rtx", 0),
                        "boost_via": event.get("boost_via", "off"),
                    }
                    self.phase = event.get("phase", self.phase)
                    self.detail = event.get("detail", self.detail)
                    if self.phase == "live" and time.monotonic() - self.last_video < 2.0:
                        self._show_live()
                    elif self.phase != "live":
                        self._show_idle(self.detail)
                    self._render_telemetry()
                elif kind == "telemetry":
                    self._render_telemetry(event)
                elif kind == "log":
                    self.last_log = event.get("text", "")
                    print(f"[*] {self.last_log}", flush=True)
                    self._render_telemetry()
        except queue.Empty:
            pass
        now = time.monotonic()
        if self.phase == "live" and now - self.last_video >= max(self.args.video_timeout, 2.0):
            self.banner.configure(text="LIVE", fg="#d8c45a")
            self.status.configure(text="эфир есть, ждём кадр")
        if self.phase == "live" and now - self.last_video >= 5.0:
            self.phase = "stalled"
            self.detail = "поток оборвался"
            self._show_idle(self.detail)
        if not self.stop.is_set():
            self.root.after(50, self.pump)

    def run(self) -> None:
        threading.Thread(target=self.engine_loop, daemon=True).start()
        threading.Thread(target=self.decoder_loop, daemon=True).start()
        threading.Thread(target=self.player_loop, daemon=True).start()
        self.root.after(50, self.pump)
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    parser.set_defaults(boost=True)
    parser.add_argument("--lut", default="", help="optional 3D .cube LUT for local display")
    parser.add_argument("--lut-intensity", type=float, default=1.0, help="LUT mix 0..1")
    parser.add_argument("--expand-43", action="store_true", help="pad 4:3 liveview to 16:9")
    parser.add_argument("--rtsp-port", type=int, default=0, help="MPEG-TS/UDP publish port (0 = off)")
    args = parser.parse_args()
    LiveApp(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
