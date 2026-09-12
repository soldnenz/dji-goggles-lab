"""Minimal /dev/raw-gadget binding for Raspberry Pi's dwc2 UDC."""
from __future__ import annotations

import ctypes
import fcntl
import os
import struct
import time

_libc = ctypes.CDLL(None, use_errno=True)
_libc.ioctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_void_p]
_libc.ioctl.restype = ctypes.c_int

USB_RAW_EVENT_CONNECT = 1
USB_RAW_EVENT_CONTROL = 2
USB_RAW_EVENT_SUSPEND = 3
USB_RAW_EVENT_RESUME = 4
USB_RAW_EVENT_RESET = 5
USB_RAW_EVENT_DISCONNECT = 6
USB_DIR_IN = 0x80
USB_TYPE_MASK = 0x60
USB_TYPE_STANDARD = 0x00
USB_TYPE_VENDOR = 0x40
USB_REQ_GET_STATUS = 0x00
USB_REQ_SET_ADDRESS = 0x05
USB_REQ_GET_DESCRIPTOR = 0x06
USB_REQ_GET_CONFIGURATION = 0x08
USB_REQ_SET_CONFIGURATION = 0x09
USB_REQ_GET_INTERFACE = 0x0A
USB_REQ_SET_INTERFACE = 0x0B
USB_DT_DEVICE = 0x01
USB_DT_CONFIG = 0x02
USB_DT_STRING = 0x03
USB_DT_DEVICE_QUALIFIER = 0x06
USB_DT_OTHER_SPEED_CONFIG = 0x07
USB_DT_BOS = 0x0F
USB_ENDPOINT_XFER_BULK = 2
AOA_GET_PROTOCOL = 0x33
AOA_SEND_STRING = 0x34
AOA_START = 0x35
AOA_PROTOCOL_VERSION = 2
PID_NORMAL = 0x4EE0
PID_ACCESSORY = 0x2D01
MAX_TRANSFER_SIZE = 4096
_EP_IO_HEADER = 8


def _ioc(direction: int, kind: str, number: int, size: int) -> int:
    return (direction << 30) | (ord(kind) << 8) | number | (size << 16)


def _io(kind: str, number: int) -> int:
    return _ioc(0, kind, number, 0)


def _ior(kind: str, number: int, size: int) -> int:
    return _ioc(2, kind, number, size)


def _iow(kind: str, number: int, size: int) -> int:
    return _ioc(1, kind, number, size)


def _iowr(kind: str, number: int, size: int) -> int:
    return _ioc(3, kind, number, size)


_INIT = _iow("U", 0, 257)
_RUN = _io("U", 1)
_EVENT_FETCH = _ior("U", 2, 8)
_EP0_WRITE = _iow("U", 3, _EP_IO_HEADER)
_EP0_READ = _iowr("U", 4, _EP_IO_HEADER)
_EP_ENABLE = _iow("U", 5, 9)
_EP_DISABLE = _iow("U", 6, 4)
_EP_WRITE = _iow("U", 7, _EP_IO_HEADER)
_EP_READ = _iowr("U", 8, _EP_IO_HEADER)
_CONFIGURE = _io("U", 9)
_VBUS_DRAW = _iow("U", 10, 4)
_EP0_STALL = _io("U", 12)


class RawGadget:
    def __init__(self, driver: str, device: str):
        self.driver, self.device, self.fd = driver, device, -1
        self._open()

    def _open(self) -> None:
        fd = os.open("/dev/raw-gadget", os.O_RDWR)
        self.fd = fd
        init = bytearray(257)
        init[: min(len(self.driver), 127)] = self.driver.encode()[:127]
        init[128:128 + min(len(self.device), 127)] = self.device.encode()[:127]
        init[256] = 3              
        try:
            fcntl.ioctl(self.fd, _INIT, bytes(init))
            fcntl.ioctl(self.fd, _RUN, 0)
        except BaseException:
            try:
                os.close(self.fd)
            finally:
                self.fd = -1
            raise

    def reinit(self, settle: float = 0.25) -> None:
        old_fd = self.fd
        self.fd = -1
        if old_fd >= 0:
            try:
                os.close(old_fd)
            except OSError:
                pass
        time.sleep(settle)
        self._open()

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1

    def _ioctl(self, request: int, buffer: bytearray) -> int:
        cbuffer = (ctypes.c_ubyte * len(buffer)).from_buffer(buffer)
        result = _libc.ioctl(self.fd, ctypes.c_ulong(request), ctypes.cast(cbuffer, ctypes.c_void_p))
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    def event_fetch(self, maximum: int = 4096) -> tuple[int, bytes]:
        buffer = bytearray(8 + maximum)
        struct.pack_into("<II", buffer, 0, 0, maximum)
        self._ioctl(_EVENT_FETCH, buffer)
        event, length = struct.unpack_from("<II", buffer, 0)
        return event, bytes(buffer[8:8 + min(length, maximum)])

    def ep0_write(self, data: bytes) -> None:
        buffer = bytearray(_EP_IO_HEADER + MAX_TRANSFER_SIZE)
        struct.pack_into("<HHI", buffer, 0, 0, 0, len(data))
        buffer[8:8 + len(data)] = data
        self._ioctl(_EP0_WRITE, buffer)

    def ep0_read(self, length: int = 0) -> bytes:
        buffer = bytearray(_EP_IO_HEADER + MAX_TRANSFER_SIZE)
        struct.pack_into("<HHI", buffer, 0, 0, 0, length)
        self._ioctl(_EP0_READ, buffer)
        actual = struct.unpack_from("<I", buffer, 4)[0]
        return bytes(buffer[8:8 + actual])

    def ep0_stall(self) -> None:
        fcntl.ioctl(self.fd, _EP0_STALL, 0)

    def configure(self) -> None:
        fcntl.ioctl(self.fd, _CONFIGURE, 0)

    def vbus_draw(self, milliamps: int = 500) -> None:
        fcntl.ioctl(self.fd, _VBUS_DRAW, struct.pack("<I", milliamps))

    def ep_enable(self, address: int, max_packet: int = 512) -> int:
        descriptor = struct.pack("<BBBBHBBB", 7, 5, address, USB_ENDPOINT_XFER_BULK, max_packet, 0, 0, 0)
        cbuffer = (ctypes.c_ubyte * len(descriptor)).from_buffer_copy(descriptor)
        result = _libc.ioctl(self.fd, ctypes.c_ulong(_EP_ENABLE), ctypes.cast(cbuffer, ctypes.c_void_p))
        if result < 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error))
        return result

    def ep_disable(self, endpoint: int) -> None:
        """Disable a Raw Gadget endpoint by its returned handle."""
        fcntl.ioctl(self.fd, _EP_DISABLE, endpoint)

    def ep_read(self, endpoint: int, length: int = MAX_TRANSFER_SIZE) -> bytes:
        buffer = bytearray(_EP_IO_HEADER + MAX_TRANSFER_SIZE)
        struct.pack_into("<HHI", buffer, 0, endpoint, 0, length)
                                                                            
                                                                          
                                                    
        result = self._ioctl(_EP_READ, buffer)
        actual = struct.unpack_from("<I", buffer, 4)[0]
        if actual == 0 and result > 0:
            actual = result
        return bytes(buffer[8:8 + min(actual, length)])

    def ep_write(self, endpoint: int, data: bytes) -> None:
        buffer = bytearray(_EP_IO_HEADER + MAX_TRANSFER_SIZE)
        struct.pack_into("<HHI", buffer, 0, endpoint, 0, len(data))
        buffer[8:8 + len(data)] = data
        self._ioctl(_EP_WRITE, buffer)


def parse_control(data: bytes) -> dict | None:
    if len(data) < 8:
        return None
    request_type, request, value, index, length = struct.unpack_from("<BBHHH", data)
    return {"type": request_type, "request": request, "value": value, "index": index, "length": length}


def device_descriptor(pid: int) -> bytes:
    return struct.pack("<BBHBBBBHHHBBBB", 18, USB_DT_DEVICE, 0x0200, 0, 0, 0, 64, 0x18D1, pid, 0x0100, 1, 2, 3, 1)


def config_descriptor() -> bytes:
    config = struct.pack("<BBHBBBBB", 9, USB_DT_CONFIG, 32, 1, 1, 0, 0x80, 250)
    interface = struct.pack("<BBBBBBBBB", 9, 4, 0, 0, 2, 0xFF, 0xFF, 0, 0)
    out_ep = struct.pack("<BBBBHB", 7, 5, 0x01, USB_ENDPOINT_XFER_BULK, 512, 0)
    in_ep = struct.pack("<BBBBHB", 7, 5, 0x81, USB_ENDPOINT_XFER_BULK, 512, 0)
    return config + interface + out_ep + in_ep


def string_descriptor(text: str = "", language: bool = False) -> bytes:
    if language:
        return struct.pack("<BBH", 4, USB_DT_STRING, 0x0409)
    encoded = text.encode("utf-16-le")
    return struct.pack("<BB", 2 + len(encoded), USB_DT_STRING) + encoded


def qualifier_descriptor() -> bytes:
    return struct.pack("<BBHBBBBBH", 10, USB_DT_DEVICE_QUALIFIER, 0x0200, 0, 0, 0, 64, 1, 0)
