"""Command-line client for :mod:`pi_endpoint.control_server`."""
from __future__ import annotations

import argparse
import json
import socket

from .control_server import DEFAULT_SOCKET


def request(socket_path: str, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5.0)
        connection.connect(socket_path)
        connection.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        data = bytearray()
        while b"\n" not in data:
            chunk = connection.recv(65536)
            if not chunk:
                break
            data.extend(chunk)
        if not data:
            raise RuntimeError("control server closed the connection")
        return json.loads(bytes(data).split(b"\n", 1)[0])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--socket", default=DEFAULT_SOCKET)
    sub = parser.add_subparsers(dest="op", required=True)
    sub.add_parser("status")
    sub.add_parser("list")
    record = sub.add_parser("record")
    record.add_argument("state", choices=("start", "stop"))
    photo = sub.add_parser("photo")
    photo.add_argument("--wait-ms", type=int, default=800)
    mode = sub.add_parser("mode")
    mode.add_argument("mode", choices=("photo", "video", "playback"))
    send = sub.add_parser("send", help="send a named command with exact payload bytes")
    send.add_argument("name")
    send.add_argument("--payload", dest="payload_hex", required=True)
    send.add_argument("--value")
    send.add_argument("--receiver-type", type=int, default=1)
    send.add_argument("--receiver-idx", type=int, default=0)
    send.add_argument("--ack-type", type=int, default=2)
    send.add_argument("--wait-ms", type=int, default=800)
    args = parser.parse_args()
    if args.op == "status":
        payload = {"op": "status"}
    elif args.op == "list":
        payload = {"op": "list"}
    elif args.op == "record":
        payload = {"op": "record", "state": args.state}
    elif args.op == "photo":
        payload = {"op": "photo", "wait_ms": args.wait_ms}
    elif args.op == "mode":
        payload = {"op": "mode", "mode": args.mode}
    else:
        payload = {
            "op": "send", "name": args.name, "payload_hex": args.payload_hex,
            "receiver_type": args.receiver_type, "receiver_idx": args.receiver_idx,
            "ack_type": args.ack_type, "wait_ms": args.wait_ms,
        }
        if args.value is not None:
            payload["value"] = args.value
    response = request(args.socket, payload)
    print(json.dumps(response, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if response.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

