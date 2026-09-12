"""Camera-control command registry for the DJI DUML camera service.

The transport is deliberately kept separate from this registry.  The same
DUML command set is used by several DJI camera/air-unit generations, but the
payload layouts are not identical on every firmware.  Commands with a proven
small payload (record/photo/mode) have convenience builders; the remaining
commands are exposed through the raw-payload API and are logged before they
are sent.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from . import duml

CAMERA_CMD_SET = 0x02
APP_TYPE = 0x02
CAMERA_TYPE = 0x01


@dataclass(frozen=True)
class CommandInfo:
    name: str
    cmd_set: int
    cmd_id: int
    description: str
    destructive: bool = False


                                                                            
                                                                            
                                                     
_CAMERA_COMMANDS = [
    ("take_photo", 0x01, "take a photo"),
    ("record_video", 0x02, "start/stop video recording"),
    ("set_liveview_source", 0x09, "select live-view source"),
    ("switch_playback", 0x0C, "switch playback mode"),
    ("set_working_mode", 0x10, "photo/video/playback working mode"),
    ("set_photo_size", 0x12, "set photo size"),
    ("set_photo_quality", 0x14, "set photo quality"),
    ("set_photo_storage_format", 0x16, "set photo storage format"),
    ("set_video_format", 0x18, "set video format"),
    ("set_video_quality", 0x1A, "set video quality"),
    ("set_video_storage_format", 0x1C, "set video storage format"),
    ("set_exposure_mode", 0x1E, "set exposure mode"),
    ("set_scene_mode", 0x20, "set scene mode"),
    ("get_scene_mode", 0x21, "get scene mode"),
    ("set_metering_mode", 0x22, "set metering mode"),
    ("set_focus_mode", 0x24, "set focus mode"),
    ("set_aperture", 0x26, "set aperture"),
    ("set_shutter", 0x28, "set shutter speed"),
    ("get_shutter", 0x29, "get shutter speed"),
    ("set_iso", 0x2A, "set ISO"),
    ("get_iso", 0x2B, "get ISO"),
    ("set_white_balance", 0x2C, "set white balance"),
    ("set_exposure_compensation", 0x2E, "set exposure compensation"),
    ("set_focus_area", 0x30, "set focus area"),
    ("set_spot_focus_area", 0x32, "set spot focus area"),
    ("get_spot_focus_area", 0x33, "get spot focus area"),
    ("set_focus_zoom", 0x34, "set focus/zoom parameters"),
    ("set_sharpness", 0x38, "set sharpness"),
    ("set_contrast", 0x3A, "set contrast"),
    ("set_saturation", 0x3C, "set saturation"),
    ("set_color_tone", 0x3E, "set color tone"),
    ("set_digital_filter", 0x42, "set digital filter"),
    ("set_denoising", 0x44, "set digital denoising"),
    ("set_anti_flicker", 0x46, "set anti-flicker"),
    ("set_continue", 0x48, "set continuous capture"),
    ("set_timelapse", 0x4A, "set timelapse"),
    ("get_timelapse", 0x4B, "get timelapse"),
    ("set_video_out", 0x4C, "set video output parameters"),
    ("get_video_out", 0x4D, "get video output parameters"),
    ("set_date", 0x54, "set camera date"),
    ("set_language", 0x56, "set camera language"),
    ("get_language", 0x57, "get camera language"),
    ("set_gps", 0x58, "set GPS coordinate"),
    ("get_gps", 0x59, "get GPS coordinate"),
    ("set_file_index_mode", 0x5C, "set file index mode"),
    ("set_aeb", 0x5E, "set AEB/continuous capture"),
    ("get_aeb", 0x5F, "get AEB/continuous capture"),
    ("set_histogram", 0x60, "enable histogram"),
    ("get_histogram", 0x61, "get histogram setting"),
    ("set_video_caption", 0x62, "set video caption"),
    ("get_video_caption", 0x63, "get video caption"),
    ("set_ntsc_pal", 0x66, "set NTSC/PAL"),
    ("set_ae_lock", 0x68, "set AE lock"),
    ("get_ae_lock", 0x69, "get AE lock"),
    ("set_capture_type", 0x6A, "set capture type"),
    ("set_recording_mode", 0x6C, "set recording mode"),
    ("set_pano_mode", 0x6E, "set panorama mode"),
    ("get_pano_mode", 0x6F, "get panorama mode"),
    ("format_sdcard", 0x72, "format camera SD card", True),
    ("save_camera_parameters", 0x77, "save camera parameters"),
    ("load_camera_parameters", 0x78, "load camera parameters"),
    ("delete_photo", 0x79, "delete a photo", True),
    ("playback_control", 0x7A, "playback control"),
    ("playback_select", 0x7B, "select playback item"),
    ("get_recording_info", 0x92, "get video recording information"),
    ("set_clip_info", 0x93, "set video clip information"),
    ("set_focus_engine", 0x95, "set focus engine value"),
    ("get_file_system_info", 0x98, "get camera file-system information"),
    ("set_audio", 0x9F, "set audio parameters"),
    ("get_audio", 0xA0, "get audio parameters"),
    ("set_lens_focal_distance", 0xA2, "set lens focal distance"),
    ("set_calibration", 0xA3, "set calibration control"),
    ("set_ae_lock_type", 0xA8, "set AE lock type"),
    ("set_video_coding_standard", 0xAB, "set H.264/H.265 coding standard"),
    ("set_pro_video_format", 0xAF, "set professional video format"),
    ("get_pro_video_format", 0xB0, "get professional video format"),
    ("request_i_frame", 0xB3, "request an I-frame"),
    ("get_sensor_id", 0xB5, "get sensor ID"),
    ("set_front_led", 0xB6, "set front LED behavior"),
    ("set_control_zoom", 0xB8, "set digital/optical zoom"),
    ("set_image_orientation", 0xB9, "set image orientation"),
    ("set_lock_gimbal_when_capture", 0xBB, "lock gimbal during capture"),
    ("set_file_tag", 0xBF, "set file tag"),
    ("set_tap_zoom", 0xC4, "enable tap zoom"),
    ("get_tap_zoom", 0xC5, "get tap zoom"),
    ("set_tap_zoom_target", 0xC6, "set tap zoom target"),
    ("get_calibration", 0xCE, "get calibration control"),
    ("set_user_data", 0xD7, "set user custom data"),
    ("get_user_data", 0xD8, "get user custom data"),
    ("storage_config", 0xDA, "camera storage configuration"),
    ("set_mode_profile", 0xE1, "set camera mode profile"),
    ("set_watermark", 0xE5, "set watermark"),
    ("set_original_photo_config", 0xE7, "set original photo storage"),
    ("get_original_photo_config", 0xE8, "get original photo storage"),
    ("subscribe_camera_status", 0xEB, "subscribe to camera status"),
    ("camera_expand", 0xFF, "camera extension command"),
]

CAMERA_COMMANDS: dict[str, CommandInfo] = {
    name: CommandInfo(name, CAMERA_CMD_SET, cmd_id, description, destructive)
    for name, cmd_id, description, *rest in _CAMERA_COMMANDS
    for destructive in [bool(rest[0]) if rest else False]
}

_ALIASES = {
    "photo": "take_photo",
    "record": "record_video",
    "mode": "set_working_mode",
    "iso": "set_iso",
    "shutter": "set_shutter",
    "wb": "set_white_balance",
    "ev": "set_exposure_compensation",
    "zoom": "set_control_zoom",
}

                                                                           
                                                                      
                               
ISO_VALUES = {
    "auto": 0x00,
    "100": 0x03,
    "200": 0x04,
    "400": 0x05,
    "800": 0x06,
    "1600": 0x07,
    "3200": 0x08,
    "6400": 0x09,
    "12800": 0x0A,
    "25600": 0x0B,
}
ISO_LABELS = {value: key for key, value in ISO_VALUES.items()}

                                                                          
                                                                           
                                                                           
                           
SHUTTER_DENOMINATORS = (
    8000, 6400, 6000, 5000, 4000, 3200, 3000, 2500, 2000, 1600,
    1500, 1250, 1000, 800, 725, 640, 500, 400, 350, 320, 250, 240,
    200, 180, 160, 125, 120, 100, 90, 80, 60, 50, 30,
)
SHUTTER_VALUES = {f"1/{denominator}": denominator for denominator in SHUTTER_DENOMINATORS}

                                                                         
                                                                             
                                                                   
VIDEO_RESOLUTION_VALUES = {
    ("16:9", "3840x2160"): 0x10,
    ("16:9", "2688x1512"): 0x2D,
    ("16:9", "1920x1080"): 0x0A,
    ("16:9", "1280x720"): 0x04,
    ("4:3", "3840x2880"): 0x67,
    ("4:3", "2688x2016"): 0x5F,
    ("4:3", "1440x1080"): 0x0C,
}
VIDEO_FPS_VALUES = {24: 0x01, 25: 0x02, 30: 0x03, 48: 0x04, 50: 0x05, 60: 0x06, 120: 0x07, 240: 0x08, 100: 0x0A}
VIDEO_FPS_LABELS = {value: key for key, value in VIDEO_FPS_VALUES.items()}


def _number(value: str | int | float | None, label: str) -> float:
    try:
        return float(value)                          
    except (TypeError, ValueError) as exc:
        raise ValueError(f"unsupported {label} value: {value}") from exc


def _kelvin(value: str | int | float | None) -> int:
    try:
        kelvin = int(float(str(value)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"white balance must be Auto or 2000..10000 K: {value}") from exc
    if not 2000 <= kelvin <= 10000 or kelvin % 100:
        raise ValueError("white balance must be Auto or a Kelvin value from 2000 to 10000 in 100 K steps")
    return kelvin


def command_info(name: str) -> CommandInfo:
    canonical = _ALIASES.get(name.lower(), name.lower())
    try:
        return CAMERA_COMMANDS[canonical]
    except KeyError as exc:
        raise ValueError(f"unknown camera command: {name}") from exc


def list_commands() -> list[dict]:
    return [
        {
            "name": info.name,
            "cmd_set": info.cmd_set,
            "cmd_id": info.cmd_id,
            "description": info.description,
            "destructive": info.destructive,
        }
        for info in CAMERA_COMMANDS.values()
    ]


def known_payload(action: str, value: str | int | None = None) -> bytes:
    """Build the camera payloads used by the DJI goggles camera path.

    The command IDs and layouts are the documented DUML camera service
    values.  A camera can still reject a valid value when that mode is not
    supported by its firmware; the endpoint reports that separately instead
    of silently changing the selected value.
    """
    canonical = _ALIASES.get(action.lower(), action.lower())
    if canonical == "record_video":
        if value in ("start", "1", 1, True):
            return b"\x01"
        if value in ("stop", "0", 0, False):
            return b"\x00"
        raise ValueError("record value must be start or stop")
    if canonical == "take_photo":
        return b"\x01" if value in (None, "single", "1", 1, True) else b"\x00"
    if canonical == "set_working_mode":
        modes = {"photo": 0, "video": 1, "playback": 2}
        if isinstance(value, str) and value.lower() in modes:
            return bytes([modes[value.lower()]])
        try:
            mode = int(value)                          
        except (TypeError, ValueError) as exc:
            raise ValueError("mode must be photo, video, playback, or 0..2") from exc
        if mode not in modes.values():
            raise ValueError("mode must be photo, video, playback, or 0..2")
        return bytes([mode])
    if canonical == "set_exposure_mode":
        modes = {"auto": 0x01, "manual": 0x04}
        try:
            mode = modes[str(value).lower()]
        except KeyError as exc:
            raise ValueError("exposure mode must be auto or manual") from exc
        return bytes([mode, 0x00])
    if canonical == "set_iso":
        try:
            return bytes([ISO_VALUES[str(value).lower()]])
        except KeyError as exc:
            raise ValueError(f"unsupported ISO value: {value}") from exc
    if canonical == "set_shutter":
        try:
            denominator = SHUTTER_VALUES[str(value)]
        except KeyError as exc:
            raise ValueError(f"unsupported shutter value: {value}") from exc
        return b"\x01" + struct.pack("<H", denominator | 0x8000) + b"\x00\x00\x00\x40"
    if canonical == "set_white_balance":
                                                                       
        presets = {"auto": (0x00, 0, 20), "sunny": (0x06, 5500, 20),
                   "cloudy": (0x06, 6500, 20), "incandescent": (0x06, 3200, 20),
                   "fluorescent": (0x06, 4000, 20)}
        key = str(value).lower()
        if key in presets:
            mode, kelvin, tint = presets[key]
        else:
            mode, kelvin, tint = 0x06, _kelvin(value), 20
        return bytes([mode]) + struct.pack("<Hh", kelvin // 100, tint)
    if canonical == "set_exposure_compensation":
        ev = _number(value, "EV")
        thirds = round(ev * 3)
                                                                             
                                                                              
                                                                 
        if abs(ev - thirds / 3) > (1 / 6 + 1e-6) or not -9 <= thirds <= 9:
            raise ValueError("EV must be between -3.0 and +3.0 in 1/3-stop steps")
        return bytes([16 + thirds])
    if canonical == "set_video_format":
        if not isinstance(value, dict):
            raise ValueError("video format must contain aspect, resolution, and fps")
        aspect = str(value.get("aspect", "16:9"))
        resolution = str(value.get("resolution", "1920x1080"))
        try:
            fps = int(value.get("fps", 30))
            resolution_value = VIDEO_RESOLUTION_VALUES[(aspect, resolution)]
            fps_value = VIDEO_FPS_VALUES[fps]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"unsupported video format: {aspect} {resolution} {value.get('fps')}") from exc
        return bytes([resolution_value, fps_value, 0x00, 0x00, 0x00])
    raise ValueError(
        f"no universal payload encoding for {action}; use an explicit payload_hex"
    )


def decode_readback(name: str, payload_hex: str | None) -> str | None:
    """Decode the small camera GET replies for the dashboard."""
    if not payload_hex:
        return None
    try:
        payload = bytes.fromhex(payload_hex)
    except ValueError:
        return None
    if name == "get_iso" and len(payload) >= 2:
        return ISO_LABELS.get(payload[1], f"index 0x{payload[1]:02x}")
    if name == "get_shutter" and len(payload) >= 4:
        denominator = int.from_bytes(payload[2:4], "little") & 0x7FFF
        return f"1/{denominator}" if denominator else "unknown"
    return None


def build_command(
    *,
    seq: int,
    name: str,
    payload: bytes,
    receiver_type: int = CAMERA_TYPE,
    receiver_idx: int = 0,
    ack_type: int = 2,
) -> bytes:
    info = command_info(name)
    return duml.build(
        sender_type=APP_TYPE,
        receiver_type=receiver_type,
        seq=seq,
        cmd_set=info.cmd_set,
        cmd_id=info.cmd_id,
        payload=payload,
        receiver_idx=receiver_idx,
        ack_type=ack_type,
    )
