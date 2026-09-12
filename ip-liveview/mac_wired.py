#!/usr/bin/env python3
"""Mac wired liveview: Goggles UDP liveview over userspace RNDIS.

Windows talks to the goggles as Remote NDIS. macOS has no RNDIS kernel driver, so
this starts tetherkit-cli (libusb + feth), assigns 192.168.60.1/24, then runs
receiver.py --wired.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time

from protocol import WIRED_LOCAL, WIRED_PEER

DJI_VID = 0x2CA3
TETHERKIT = shutil.which("tetherkit-cli") or "/opt/homebrew/bin/tetherkit-cli"


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, check=check)


def list_usb() -> list[str]:
    lines: list[str] = []
    try:
        import usb.core
        import usb.util
    except ImportError:
        return ["pyusb not installed"]
    for dev in usb.core.find(find_all=True) or []:
        try:
            maker = usb.util.get_string(dev, dev.iManufacturer) if dev.iManufacturer else ""
            prod = usb.util.get_string(dev, dev.iProduct) if dev.iProduct else ""
        except Exception:
            maker = prod = ""
        mark = "  <--- DJI" if dev.idVendor == DJI_VID else ""
        lines.append(f"  {dev.idVendor:04x}:{dev.idProduct:04x} {maker} {prod}{mark}")
    return lines


def rndis_list() -> str:
    if not os.path.exists(TETHERKIT):
        return ""
    try:
        out = run([TETHERKIT, "--list", "--lang", "en"], check=False)
    except OSError:
        return ""
    return (out.stdout or "") + (out.stderr or "")


def has_rndis() -> bool:
    text = rndis_list().lower()
    if not text.strip():
        return False
    return "no rndis device found" not in text


def iface_up(name: str) -> bool:
    out = run(["/sbin/ifconfig", name], check=False)
    return out.returncode == 0 and "RUNNING" in (out.stdout or "")


def wait_iface(name: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if iface_up(name) or run(["/sbin/ifconfig", name], check=False).returncode == 0:
            return True
        time.sleep(0.2)
    return False


def configure_ip(name: str, addr: str) -> None:
    run(["/usr/bin/sudo", "-n", "/sbin/ifconfig", name, "inet", addr, "netmask", "255.255.255.0", "up"], check=False)
    # sudo -n fails if there is no cached ticket; fall back to a prompt.
    result = run(["/sbin/ifconfig", name], check=False)
    if addr not in (result.stdout or ""):
        run(["/usr/bin/sudo", "/sbin/ifconfig", name, "inet", addr, "netmask", "255.255.255.0", "up"])


def already_wired() -> str:
    out = run(["/sbin/ifconfig"], check=False)
    text = out.stdout or ""
    current = ""
    for line in text.splitlines():
        if line and not line[0].isspace():
            current = line.split(":")[0]
        if f"inet {WIRED_LOCAL}" in line:
            return current
    return ""


def start_tetherkit(vid: int) -> subprocess.Popen[str]:
    if not os.path.exists(TETHERKIT):
        raise SystemExit(
            "tetherkit-cli not found. Install:\n"
            "  brew tap XiaoMiku01/tap && brew install XiaoMiku01/tap/tetherkit-cli"
        )
    cmd = [
        "/usr/bin/sudo",
        TETHERKIT,
        "--vid",
        f"{vid:x}",
        "--lang",
        "en",
        "--stats",
        "2000",
        "--log",
        "info",
    ]
    log(f"[*] start {' '.join(cmd)}")
    return subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="live.h264")
    parser.add_argument("--vid", default=hex(DJI_VID), help="USB vendor id (default DJI 0x2ca3)")
    parser.add_argument("--iface", default="feth0")
    parser.add_argument("--no-tether", action="store_true", help="skip tetherkit; only configure IP + receiver")
    parser.add_argument("--view", action="store_true", help="open live video + telemetry windows instead of CLI dump")
    parser.add_argument("--boost", action="store_true", help="bitrate boost via USB MI04 (on by default with --view)")
    parser.add_argument("--no-boost", action="store_true", help="disable bitrate-boost DUML")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    vid = int(args.vid, 0)

    log("Mac wired = goggles UDP liveview, with userspace RNDIS instead of a Windows driver.")
    log("Cable: goggles USB-C  ->  data cable  ->  USB-A on the Mac (hub is fine).")
    log("Do NOT use OTG on the goggles. OTG = phone path, Mac will not see RNDIS.")
    log("")
    log("[*] USB now:")
    usb = list_usb()
    log("\n".join(usb) if usb else "  (none visible to libusb)")
    log("[*] tetherkit --list:")
    listed = rndis_list().strip() or "(tetherkit missing)"
    log(listed)
    log("")

    existing = already_wired()
    tether: subprocess.Popen[str] | None = None
    try:
        if existing and args.no_tether:
            log(f"[+] {existing} already has {WIRED_LOCAL}")
            iface = existing
        elif args.no_tether:
            configure_ip(args.iface, WIRED_LOCAL)
            iface = args.iface
        else:
            if not has_rndis():
                log("[*] no RNDIS yet — plug the goggles (no OTG), waiting 60s...")
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline and not has_rndis():
                    time.sleep(1)
                if not has_rndis():
                    log("[!] tetherkit still sees no RNDIS device.")
                    log("    Mac as USB host, goggles as device. USB-A, not OTG.")
                    return 1
            tether = start_tetherkit(vid)
            if not wait_iface(args.iface, 15):
                log(f"[!] {args.iface} did not appear")
                return 1
            configure_ip(args.iface, WIRED_LOCAL)
            iface = args.iface
            log(f"[+] {iface} {WIRED_LOCAL}/24  peer {WIRED_PEER[0]}:{WIRED_PEER[1]}")

        receiver = os.path.join(os.path.dirname(os.path.abspath(__file__)), "liveview.py" if args.view else "receiver.py")
        cmd = [
            sys.executable,
            receiver,
            "--wired",
            "--bind",
            WIRED_LOCAL,
            "--out",
            args.out,
        ]
        if args.verbose:
            cmd.append("-v")
        if args.no_boost:
            cmd.append("--no-boost")
        elif args.boost or args.view:
            cmd.append("--boost")
        log(f"[*] {' '.join(cmd)}")
        proc = subprocess.Popen(cmd)
        return proc.wait()
    except KeyboardInterrupt:
        log("\n[*] stop")
        return 0
    finally:
        if tether is not None and tether.poll() is None:
            tether.send_signal(signal.SIGINT)
            try:
                tether.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tether.kill()


if __name__ == "__main__":
    raise SystemExit(main())
