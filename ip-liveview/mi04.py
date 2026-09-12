"""DJI Goggles 3 MI04 USB control (vendor interface 4, parallel to RNDIS).

Windows hardware ID is USB\\VID_2CA3&PID_0020&MI_04: composite interface 4,
vendor class ff/43/01, bulk OUT+IN. TetherKit only claims RNDIS (if 0+1), so
this interface can be opened in parallel. Do not set_configuration or reset.
"""
from __future__ import annotations

DJI_VID = 0x2CA3
DJI_PID = 0x0020
MI04_IFACE = 4


class Mi04:
    def __init__(self) -> None:
        self.dev = None
        self.out_ep = None
        self.in_ep = None
        self.claimed = False
        self.detail = "MI04 нет"

    def open(self) -> str | None:
        try:
            import usb.core
            import usb.util
        except ImportError:
            self.detail = "pyusb не установлен"
            return self.detail
        dev = usb.core.find(idVendor=DJI_VID, idProduct=DJI_PID)
        if dev is None:
            self.detail = "очки 2ca3:0020 не видны"
            return self.detail
        cfg = dev.get_active_configuration()
        intf = usb.util.find_descriptor(cfg, bInterfaceNumber=MI04_IFACE)
        if intf is None:
            self.detail = f"нет interface {MI04_IFACE}"
            return self.detail
        try:
            if dev.is_kernel_driver_active(MI04_IFACE):
                dev.detach_kernel_driver(MI04_IFACE)
        except Exception:
            pass
        try:
            usb.util.claim_interface(dev, MI04_IFACE)
        except Exception as exc:
            self.detail = f"не удалось claim MI04: {exc}"
            return self.detail
        out_ep = in_ep = None
        for ep in intf:
            if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
                out_ep = ep
            else:
                in_ep = ep
        if out_ep is None:
            usb.util.release_interface(dev, MI04_IFACE)
            self.detail = "нет bulk OUT на MI04"
            return self.detail
        self.dev = dev
        self.out_ep = out_ep
        self.in_ep = in_ep
        self.claimed = True
        self.detail = f"MI04 opened through device=2ca3:0020 out=0x{out_ep.bEndpointAddress:02x} in=0x{in_ep.bEndpointAddress:02x}"
        return None

    def write(self, payload: bytes, timeout: int = 250) -> bool:
        if not self.claimed or self.out_ep is None:
            return False
        try:
            self.out_ep.write(payload, timeout=timeout)
            return True
        except Exception:
            return False

    def close(self) -> None:
        if not self.claimed or self.dev is None:
            return
        try:
            import usb.util

            usb.util.release_interface(self.dev, MI04_IFACE)
        except Exception:
            pass
        self.dev = None
        self.out_ep = None
        self.in_ep = None
        self.claimed = False
        self.detail = "MI04 закрыт"
