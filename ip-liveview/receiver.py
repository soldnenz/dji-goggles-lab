#!/usr/bin/env python3
"""Receive DJI Goggles 3 liveview over the goggles' own IP link.

The goggles share liveview (Wi-Fi AP or USB RNDIS). This process joins that
network and speaks the UDP liveview protocol: handshake, type-2 video,
type-4 ACK with optional RTX. It does not pretend to be a USB accessory.
"""
from __future__ import annotations

import argparse
import errno
import random
import select
import socket
import sys
import time
from collections.abc import Callable
from typing import Any

from mi04 import Mi04
from protocol import (
    BOOST_INTERVAL,
    BOOST_KBPS,
    CMDSET_NAME,
    DEVICE_NAME,
    TYPE_HANDSHAKE,
    WIFI_PEER,
    WIRED_LOCAL,
    WIRED_PEER,
    FrameAssembler,
    LossWindow,
    build_ack,
    build_bitrate_boost,
    build_handshake,
    build_type5,
    handshake_seed,
    parse_data,
    parse_header,
    parse_video,
)

EventFn = Callable[[dict[str, Any]], None]


def local_ipv4() -> set[str]:
    addrs: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            addrs.add(info[4][0])
    except OSError:
        pass
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.168.2.1", 9003))
        addrs.add(probe.getsockname()[0])
    except OSError:
        pass
    try:
        probe.connect(("192.168.60.2", 9003))
        addrs.add(probe.getsockname()[0])
    except OSError:
        pass
    probe.close()
    return {ip for ip in addrs if not ip.startswith("127.")}


def bind_udp(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    except OSError:
        pass
    sock.bind((host, port))
    sock.setblocking(False)
    return sock


def recv_burst(sock: socket.socket, limit: int = 64) -> list[tuple[bytes, tuple[str, int]]]:
    """Drain the UDP socket. One recvfrom per loop drops 1080p on USB RNDIS."""
    batch: list[tuple[bytes, tuple[str, int]]] = []
    try:
        while len(batch) < limit:
            payload, addr = sock.recvfrom(65535)
            batch.append((payload, addr))
    except BlockingIOError:
        pass
    except OSError:
        if not batch:
            raise
    return batch


def peers_from_args(args: argparse.Namespace) -> list[tuple[str, tuple[str, int]]]:
    if args.peer:
        host, port = args.peer.rsplit(":", 1)
        return [("manual", (host, int(port)))]
    peers: list[tuple[str, tuple[str, int]]] = []
    if args.wifi:
        peers.append(("wifi", WIFI_PEER))
    if args.wired:
        peers.append(("wired", WIRED_PEER))
    if not peers:
        peers = [("wifi", WIFI_PEER), ("wired", WIRED_PEER)]
    return peers


def _sendto(sock: socket.socket, payload: bytes, addr: tuple[str, int]) -> bool:
    try:
        sock.sendto(payload, addr)
        return True
    except OSError as exc:
        if exc.errno in (errno.EADDRNOTAVAIL, errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EINVAL):
            return False
        raise


def format_duml(chunk: dict) -> str:
    src = DEVICE_NAME.get(chunk["sender"], f"0x{chunk['sender']:02x}")
    dst = DEVICE_NAME.get(chunk["receiver"], f"0x{chunk['receiver']:02x}")
    set_name = CMDSET_NAME.get(chunk["cmdset"], f"set{chunk['cmdset']:02x}")
    return (
        f"{src}->{dst} {set_name}.{chunk['cmd']:02x} "
        f"t={chunk['cmd_type']} seq={chunk['seq']} {chunk['payload'].hex()} {chunk['ascii']}"
    )


class Session:
    def __init__(self, args: argparse.Namespace, on_event: EventFn | None = None) -> None:
        self.args = args
        self.on_event = on_event or (lambda _e: None)

    def emit(self, kind: str, **kwargs: Any) -> None:
        self.on_event({"kind": kind, **kwargs})

    def run(self) -> int:
        args = self.args
        session = args.session if args.session is not None else (random.randrange(0x10000) | 1)
        handshake = build_handshake(session)
        seed = handshake_seed(handshake)
        assembler = FrameAssembler()
        rtx = LossWindow(seed)
        window = seed
        joined: tuple[str, tuple[str, int]] | None = None
        linked: tuple[str, tuple[str, int]] | None = None
        last_handshake = 0.0
        last_video = 0.0
        last_ctrl = 0.0
        last_ack = 0.0
        last_stats = 0.0
        last_boost = 0.0
        last_mi04_try = 0.0
        boost_seq = 0
        boost_duml = b""
        boost_via = "off"
        mi04 = Mi04()
        mi04_logged_fail = False
        type5_seq = seed
        type5_counter = 1
        type5_win = (seed, seed)
        bytes_window = 0
        frames_window = 0
        fps = 0.0
        kbps = 0.0
        dests = peers_from_args(args)
        bind_host = args.bind
        if not bind_host:
            addrs = local_ipv4()
            bind_host = WIRED_LOCAL if WIRED_LOCAL in addrs else "0.0.0.0"
        seed_win = (seed, seed)
        out = None
        play = None
        sock: socket.socket | None = None
        self.emit("status", phase="idle", detail="нет линка", session=session, bind=bind_host)
        try:
            while True:
                if sock is None:
                    try:
                        sock = bind_udp(bind_host, args.local_port)
                    except OSError:
                        self.emit("status", phase="unplugged", detail="кабель / RNDIS нет", session=session)
                        time.sleep(0.4)
                        continue
                    if out is None and args.out and args.out != "-":
                        out = open(args.out, "wb", buffering=1024 * 1024)
                    elif out is None and args.out == "-":
                        out = sys.stdout.buffer
                    if play is None and args.play:
                        play = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self.emit(
                        "log",
                        text=(
                            f"bind {bind_host}:{sock.getsockname()[1]} "
                            f"session=0x{session:04x} peers={[p[1] for p in dests]}"
                        ),
                    )
                    last_handshake = 0.0

                now = time.monotonic()
                ctrl_alive = linked is not None and now - last_ctrl <= args.video_timeout
                video_alive = joined is not None and now - last_video <= args.video_timeout
                if joined is not None and not video_alive:
                    joined = None
                    rtx.reset()
                    assembler.parts.clear()
                    self.emit("status", phase="stalled", detail="поток оборвался", session=session)
                if linked is not None and not ctrl_alive:
                    linked = None
                    self.emit("status", phase="idle", detail="нет линка", session=session)

                if now - last_stats >= 1.0:
                    fps = frames_window / max(now - last_stats, 0.001)
                    kbps = bytes_window * 8 / max(now - last_stats, 0.001) / 1000
                    frames_window = 0
                    bytes_window = 0
                    last_stats = now
                    phase = "live" if video_alive else ("telemetry" if ctrl_alive else "idle")
                    detail = {
                        "live": "эфир",
                        "telemetry": "телеметрия, нет камеры",
                        "idle": "нет линка",
                        "stalled": "поток оборвался",
                        "unplugged": "кабель / RNDIS нет",
                    }.get(phase, phase)
                    self.emit(
                        "stats",
                        phase=phase,
                        detail=detail,
                        fps=fps,
                        kbps=kbps,
                        frames=assembler.complete,
                        rtx=rtx.requests,
                        window_start=rtx.start,
                        window_end=rtx.end,
                        boost_via=boost_via,
                    )

                resend: list[int] = []
                if video_alive and args.rtx:
                    resend = rtx.missing()
                if rtx.armed:
                    ack_win_s, ack_win_e = rtx.start, rtx.end
                else:
                    ack_win_s = ack_win_e = seed
                if args.boost and not mi04.claimed and now - last_mi04_try >= 2.0:
                    last_mi04_try = now
                    err = mi04.open()
                    if err is None:
                        self.emit("log", text=mi04.detail)
                        mi04_logged_fail = False
                    elif not mi04_logged_fail:
                        self.emit("log", text=f"boost USB: {err}; пока UDP type-5")
                        mi04_logged_fail = True
                if args.boost and now - last_boost >= args.boost_interval:
                    pkt = build_bitrate_boost(boost_seq, args.boost_kbps)
                    sent = False
                    if mi04.claimed:
                        sent = mi04.write(pkt)
                        if sent:
                            boost_via = "mi04"
                            boost_seq = (boost_seq + 1) & 0xFFFF
                            last_boost = now
                        boost_duml = b""
                    elif linked is not None:
                        boost_duml = pkt
                        boost_seq = (boost_seq + 1) & 0xFFFF
                        type5_seq = (type5_seq + 8) & 0xFFFF
                        type5_win = (seed, type5_seq)
                        if not _sendto(
                            sock,
                            build_type5(session, type5_seq, seed, type5_seq, boost_duml, type5_counter),
                            linked[1],
                        ):
                            sock.close()
                            sock = None
                            linked = joined = None
                            self.emit("status", phase="unplugged", detail="кабель / RNDIS нет", session=session)
                            continue
                        type5_counter = (type5_counter + 1) & 0xFF
                        boost_via = "udp"
                        last_boost = now
                    else:
                        boost_duml = b""
                else:
                    boost_duml = b""
                if linked is not None and now - last_ack >= args.ack_interval:
                    duml, boost_duml = boost_duml, b""
                    if not _sendto(
                        sock,
                        build_ack(
                            session,
                            ack_win_s,
                            ack_win_e,
                            resend,
                            type3=seed_win,
                            type5=type5_win,
                            duml=duml,
                        ),
                        linked[1],
                    ):
                        sock.close()
                        sock = None
                        linked = joined = None
                        self.emit("status", phase="unplugged", detail="кабель / RNDIS нет", session=session)
                        continue
                    last_ack = now

                if not video_alive and not ctrl_alive:
                    if now - last_handshake >= args.handshake_interval:
                        ok = True
                        for name, peer in dests:
                            if not _sendto(sock, handshake, peer):
                                ok = False
                                break
                            self.emit("log", text=f"handshake {name} {peer[0]}:{peer[1]}")
                        last_handshake = now
                        if not ok:
                            sock.close()
                            sock = None
                            self.emit("status", phase="unplugged", detail="кабель / RNDIS нет", session=session)
                            continue
                    if args.handshake_limit and assembler.complete == 0:
                        pass

                timeout = min(0.05, args.ack_interval)
                try:
                    ready, _, _ = select.select([sock], [], [], timeout)
                except (OSError, ValueError):
                    sock.close()
                    sock = None
                    continue
                if not ready:
                    continue
                try:
                    batch = recv_burst(sock)
                except OSError:
                    sock.close()
                    sock = None
                    linked = joined = None
                    self.emit("status", phase="unplugged", detail="кабель / RNDIS нет", session=session)
                    continue
                for payload, addr in batch:
                    header = parse_header(payload)
                    if header is None:
                        continue
                    name = next((n for n, p in dests if p[0] == addr[0]), addr[0])
                    peer = (addr[0], addr[1])
                    if header["type"] == TYPE_HANDSHAKE:
                        linked = (name, peer)
                        last_ctrl = now
                        self.emit(
                            "status",
                            phase="telemetry",
                            detail="телеметрия, нет камеры",
                            session=session,
                            peer=peer,
                        )
                        _sendto(sock, build_ack(session, seed, seed, type3=seed_win, type5=seed_win), peer)
                        last_ack = now
                        continue
                    data = parse_data(payload)
                    if data is not None:
                        if linked is None:
                            linked = (name, peer)
                        last_ctrl = now
                        tele = {
                            "peer": f"{addr[0]}:{addr[1]}",
                            "name": name,
                            "session": data["session"],
                            "seq": data["seq"],
                            "length": data["length"],
                            "win2": f"{data['window_start']:04x}:{data['window_end']:04x}",
                            "win3": f"{data.get('type3_start', 0):04x}:{data.get('type3_end', 0):04x}",
                            "win5": f"{data.get('type5_start', 0):04x}:{data.get('type5_end', 0):04x}",
                            "serial": data.get("serial") or "",
                            "duml": [format_duml(c) for c in data.get("duml") or []],
                            "raw_tail": payload[32:].hex() if len(payload) > 32 else "",
                        }
                        self.emit("telemetry", **tele)
                        duml, boost_duml = boost_duml, b""
                        _sendto(
                            sock,
                            build_ack(
                                session,
                                ack_win_s,
                                ack_win_e,
                                resend if args.rtx else [],
                                type3=seed_win,
                                type5=type5_win,
                                duml=duml,
                            ),
                            peer,
                        )
                        last_ack = now
                        continue
                    video = parse_video(payload)
                    if video is None:
                        self.emit("unknown", packet_type=header["type"], length=len(payload), addr=addr)
                        continue
                    gaps = rtx.push(video["seq"]) if args.rtx else []
                    if joined is None:
                        joined = (name, peer)
                        linked = (name, peer)
                        self.emit("status", phase="live", detail="эфир", session=session, peer=peer)
                    elif joined[1][0] != addr[0]:
                        continue
                    last_video = now
                    last_ctrl = now
                    window = video["seq"]
                    frame = assembler.push(video)
                    last_part = video["part"] == video["n_parts"] - 1
                    use_resend = gaps if args.rtx else []
                    win_s = rtx.start if rtx.armed else seed
                    win_e = rtx.end if rtx.armed else seed
                    if last_part or args.ack_every or use_resend:
                        duml, boost_duml = boost_duml, b""
                        _sendto(
                            sock,
                            build_ack(
                                session,
                                win_s,
                                win_e,
                                use_resend,
                                type3=seed_win,
                                type5=type5_win,
                                duml=duml,
                            ),
                            joined[1],
                        )
                        last_ack = now
                    if frame is None:
                        continue
                    frames_window += 1
                    bytes_window += len(frame)
                    if out is not None:
                        out.write(frame)
                    if play is not None:
                        play.sendto(frame, ("127.0.0.1", args.play_port))
                    self.emit(
                        "frame",
                        h264=frame,
                        index=video["frame"],
                        parts=video["n_parts"],
                        seq=video["seq"],
                        bytes=len(frame),
                        complete=assembler.complete,
                        rtx_gaps=use_resend,
                    )
        except KeyboardInterrupt:
            self.emit("log", text="stop")
            return 0
        finally:
            mi04.close()
            if sock is not None:
                sock.close()
            if out is not None and out is not sys.stdout.buffer:
                out.close()
            if play is not None:
                play.close()


def add_common_args(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--out", default="live.h264", help="Annex-B H.264 file, or - for stdout")
    parser.add_argument("--bind", default="", help="local IPv4; default 192.168.60.1 if present else 0.0.0.0")
    parser.add_argument("--local-port", type=int, default=0, help="local UDP port, 0 = ephemeral")
    parser.add_argument("--peer", help="override remote host:port")
    parser.add_argument("--wifi", action="store_true", help="only 192.168.2.1:9003")
    parser.add_argument("--wired", action="store_true", help="only 192.168.60.2:9003")
    parser.add_argument("--session", type=lambda s: int(s, 0), help="16-bit session id (default random)")
    parser.add_argument("--handshake-interval", type=float, default=1.0)
    parser.add_argument("--handshake-limit", type=int, default=0, help="give up after N probes; 0 = forever")
    parser.add_argument("--video-timeout", type=float, default=1.0)
    parser.add_argument("--ack-every", action="store_true", help="ACK every video packet, not only end-of-frame")
    parser.add_argument("--ack-interval", type=float, default=1.0 / 30.0, help="type-4 keepalive period while linked")
    parser.add_argument("--play", action="store_true", help="also UDP-forward H.264 to 127.0.0.1:--play-port")
    parser.add_argument("--play-port", type=int, default=5004)
    parser.add_argument("--rtx", dest="rtx", action="store_true", default=True, help="request missing type-2 seqs (Loss recovery)")
    parser.add_argument("--no-rtx", dest="rtx", action="store_false", help="do not send RTX resend list")
    parser.add_argument(
        "--boost",
        dest="boost",
        action="store_true",
        default=False,
        help="bitrate hint via USB MI04 (22500 kbps / 250 ms). RTX stays on UDP.",
    )
    parser.add_argument("--no-boost", dest="boost", action="store_false", help="do not piggy-back bitrate DUML")
    parser.add_argument("--boost-kbps", type=int, default=BOOST_KBPS, help="boost feedback bitrate (default 22500)")
    parser.add_argument("--boost-interval", type=float, default=BOOST_INTERVAL, help="boost DUML period in seconds (default 0.25)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def run(args: argparse.Namespace) -> int:
    def on_event(event: dict[str, Any]) -> None:
        kind = event.get("kind")
        if kind == "log":
            print(f"[*] {event['text']}", flush=True)
        elif kind == "status" and args.verbose:
            print(f"[*] {event.get('phase')} {event.get('detail')}", flush=True)
        elif kind == "frame" and args.verbose:
            print(
                f"frame {event['index']} parts={event['parts']} "
                f"bytes={event['bytes']} seq={event['seq']}",
                flush=True,
            )
        elif kind == "telemetry" and args.verbose and event.get("duml"):
            for line in event["duml"]:
                print(f"    duml {line}", flush=True)
        elif kind == "stats" and args.verbose:
            print(
                f"[*] {event['detail']} fps={event['fps']:.1f} {event['kbps']:.0f} kbps "
                f"via={event.get('boost_via', 'off')} frames={event['frames']} rtx={event['rtx']}",
                flush=True,
            )

    return Session(args, on_event).run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_common_args(parser)
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
