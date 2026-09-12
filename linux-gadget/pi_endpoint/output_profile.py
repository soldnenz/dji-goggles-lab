"""Validated HDMI pipeline profile shared by the UI and the video worker."""
from __future__ import annotations

import json
import os
import re
import shlex
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_PATH = "/var/lib/dji-pi-receiver/settings.json"
FALLBACK_VIDEO_CANDIDATES = (
    "/opt/goggles-lab/assets/no-signal.mp4",
    "/opt/goggles-lab/assets/no-signal.mp4",
    "/opt/goggles-lab/assets/no-signal.mp4",
)
ROTATION_METHODS = {90: "clockwise", 180: "rotate-180", -90: "counterclockwise"}
RESOLUTIONS = {
    "1920x1080": (1920, 1080),
    "1680x1050": (1680, 1050),
    "1600x900": (1600, 900),
    "1440x1080": (1440, 1080),
    "1440x900": (1440, 900),
    "1280x1024": (1280, 1024),
    "1280x800": (1280, 800),
    "1280x720": (1280, 720),
    "1152x864": (1152, 864),
    "1024x768": (1024, 768),
    "960x720": (960, 720),
    "832x624": (832, 624),
    "800x600": (800, 600),
    "720x576": (720, 576),
    "720x480": (720, 480),
    "640x480": (640, 480),
    "720x400": (720, 400),
}


def load_settings(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def profile_from_settings(settings: dict[str, Any]) -> dict[str, Any]:
    video = settings.get("video", {}) if isinstance(settings, dict) else {}
                                                                                          
    resolution = "1920x1080"
    fps = int(video.get("fps", 30))
    if fps not in {25, 30, 50, 60}:
        fps = 30
    rotation = int(video.get("rotation", 0))
    if rotation not in {-90, 0, 90, 180}:
        rotation = 0
    scan = str(video.get("scan", "progressive"))
    if scan not in {"progressive", "interlaced", "auto"}:
        scan = "progressive"
    output = str(video.get("hdmi_output", "all"))
    if output not in {"all", "1", "2"}:
        output = "all"
    pending = []
    if output == "all":
        pending.append("multi_hdmi")
    if output == "1" and not os.environ.get("DJI_HDMI_CONNECTOR_1"):
        pending.append("hdmi_1_connector_id")
    if bool(video.get("ntsc", False)):
        pending.append("ntsc_drm_timing")
    return {
        "resolution": resolution,
        "fps": fps,
        "rotation": rotation,
        "scan": scan,
        "ntsc": bool(video.get("ntsc", False)),
        "hdmi_output": output,
        "pending": pending,
    }


def _connected_id(connectors: dict[str, dict[str, Any]], name: str) -> str | None:
    info = connectors.get(name) or {}
    if info.get("connected") and info.get("id"):
        return str(info["id"])
    return None


def _present_id(connectors: dict[str, dict[str, Any]], name: str) -> str | None:
    info = connectors.get(name) or {}
    if info.get("id") and info.get("present", info.get("connected")):
        return str(info["id"])
    return None


def _connected_ids(connectors: dict[str, dict[str, Any]]) -> list[str]:
    return [str(info["id"]) for info in connectors.values() if info.get("connected") and info.get("id")]


def connector_id(output: str, command: list[str], connectors: dict[str, dict[str, Any]] | None = None) -> str | None:
    """Prefer a live DRM connector over a hardcoded kmssink placeholder."""
    connectors = connectors if connectors is not None else discover_connectors()
    env1 = os.environ.get("DJI_HDMI_CONNECTOR_1")
    env2 = os.environ.get("DJI_HDMI_CONNECTOR_2")
    if output == "1":
        return env1 or _connected_id(connectors, "HDMI-A-1")
    if output == "2":
        return env2 or _connected_id(connectors, "HDMI-A-2") or _present_id(connectors, "HDMI-A-2") or _connected_id(connectors, "HDMI-A-1") or next(iter(_connected_ids(connectors)), None)
    ids = []
    for name, env in (("HDMI-A-1", env1), ("HDMI-A-2", env2)):
        value = env or _connected_id(connectors, name)
        if value:
            ids.append(value)
    if ids:
        return ids[0]
    connected = _connected_ids(connectors)
    if connected:
        return connected[0]
    for index, token in enumerate(command):
        if token == "connector-id" and index + 1 < len(command):
            return command[index + 1]
        if token.startswith("connector-id="):
            return token.split("=", 1)[1]
    return None


def _leaky_queue() -> list[str]:
    return [
        "queue",
        "leaky=downstream",
        "max-size-buffers=3",
        "max-size-bytes=0",
        "max-size-time=0",
        "!",
    ]


def discover_connectors() -> dict[str, dict[str, Any]]:
    """Read HDMI connector ids from sysfs.

    kmsprint talks to DRM and can block in D-state on a wedged vc4, so the
    live player must not wait on it to choose a connector.
    """
    result: dict[str, dict[str, Any]] = {}
    for path in Path("/sys/class/drm").glob("card*-HDMI-A-*"):
        try:
            name = "HDMI-A-" + path.name.rsplit("-", 1)[-1]
            status = (path / "status").read_text().strip()
            connected = status == "connected"
            info = {
                "id": str(int((path / "connector_id").read_text().strip())),
                "connected": connected,
                "present": status != "disconnected",
            }
            existing = result.get(name)
            if existing is None or (connected and not existing.get("connected")):
                result[name] = info
        except (OSError, ValueError):
            continue
    return result


def discover_interlaced_connectors() -> set[str]:
    """Interlaced probing used kmsprint -m, which can hang the same DRM path."""
    return set()


def _replace_connector(command: list[str], value: str) -> list[str]:
    result = list(command)
    for index, token in enumerate(result):
        if token == "connector-id" and index + 1 < len(result):
            result[index + 1] = value
        elif token.startswith("connector-id="):
            result[index] = f"connector-id={value}"
    return result


def build_command(base: str | list[str] | None, settings_path: str | None = None) -> tuple[list[str], dict[str, Any]]:
    """Add bounded conversion filters to the existing gst-launch command.

    The H.264 USB reader remains untouched. If no gst-launch command is
    configured, the empty command is returned and the raw dump path continues
    to work as before.
    """
    command = shlex.split(base) if isinstance(base, str) else list(base or [])
    settings = load_settings(settings_path)
    profile = profile_from_settings(settings)
    if not command or "kmssink" not in command:
        return command, {**profile, "applied": False, "reason": "no kmssink command"}

    connectors = discover_connectors()
    interlaced_connectors = discover_interlaced_connectors()
    connector_one = os.environ.get("DJI_HDMI_CONNECTOR_1") or _connected_id(connectors, "HDMI-A-1")
    connector_two = os.environ.get("DJI_HDMI_CONNECTOR_2") or _connected_id(connectors, "HDMI-A-2")
    both_available = False
    if profile["hdmi_output"] == "1" and connector_one:
        command = _replace_connector(command, connector_one)
        profile["pending"] = [item for item in profile["pending"] if item != "hdmi_1_connector_id"]
    elif profile["hdmi_output"] == "2":
        chosen = connector_id("2", command, connectors)
        if chosen:
            command = _replace_connector(command, chosen)
    elif profile["hdmi_output"] == "all":
        both_available = bool(connector_one and connector_two)
        if both_available:
            profile["pending"] = [item for item in profile["pending"] if item != "multi_hdmi"]
        elif connector_one or connector_two or _connected_ids(connectors):
                                                                            
                                                    
            profile["pending"] = [item for item in profile["pending"] if item != "multi_hdmi"]
            chosen = connector_one or connector_two or next(iter(_connected_ids(connectors)), None)
            if chosen:
                command = _replace_connector(command, chosen)

    if profile["scan"] == "interlaced" and connectors:
        requested = {"HDMI-A-1", "HDMI-A-2"} if profile["hdmi_output"] == "all" else {f"HDMI-A-{profile['hdmi_output']}"}
        if not requested.intersection(interlaced_connectors):
            profile["pending"].append("interlaced_mode_unavailable")

    passthrough = (
        profile["resolution"] == "1920x1080"
        and profile["fps"] == 30
        and profile["rotation"] == 0
        and profile["scan"] in {"progressive", "auto"}
    )
    if passthrough:
        if profile["hdmi_output"] == "all" and both_available and not profile["pending"]:
            sink_index = command.index("kmssink")
            prefix = command[:sink_index]
            sink_args = command[sink_index + 1:]
            first_sink = _replace_connector(sink_args, connector_one)
            second_sink = _replace_connector(sink_args, connector_two)
            command = prefix + ["tee", "name=display_tee", "!", *_leaky_queue(), "kmssink"] + first_sink + ["display_tee.", "!", *_leaky_queue(), "kmssink"] + second_sink
        return command, {**profile, "applied": not profile["pending"], "conversion": "passthrough"}

    sink_index = command.index("kmssink")
    prefix = command[:sink_index]
    sink_args = command[sink_index + 1:]
    filters: list[str] = []
    if profile["rotation"] in ROTATION_METHODS:
        filters += ["videoflip", f"method={ROTATION_METHODS[profile['rotation']]}", "!"]
        if abs(profile["rotation"]) == 90:
            filters += ["videoscale", "add-borders=true", "!", "video/x-raw,width=1920,height=1080,pixel-aspect-ratio=1/1", "!"]
    if profile["fps"] != 30:
                                                                             
                                                                            
        filters += ["videorate", "!", f"video/x-raw,framerate={profile['fps']}/1", "!"]
    if profile["scan"] == "interlaced" and "interlaced_mode_unavailable" not in profile["pending"]:
        filters += ["interlace", "!"]

    converted = prefix + filters + _leaky_queue() + ["kmssink"] + sink_args
    if profile["hdmi_output"] == "all" and both_available and not profile["pending"]:
        first_sink = _replace_connector(sink_args, connector_one)
        second_sink = _replace_connector(sink_args, connector_two)
        converted = prefix + filters + [
            "tee", "name=display_tee", "!", *_leaky_queue(), "kmssink",
            *first_sink, "display_tee.", "!", *_leaky_queue(), "kmssink", *second_sink,
        ]
    return converted, {
        **profile,
        "applied": not profile["pending"],
        "conversion": "videoflip-videoscale-videorate" if filters else "passthrough",
    }


def describe(command: list[str] | None, settings_path: str | None) -> dict[str, Any]:
    effective, profile = build_command(command, settings_path)
    return {"profile": profile, "command": shlex.join(effective) if effective else ""}


def resolve_fallback_video(path: str | None) -> str | None:
    """Prefer the packaged MP4, then the skeleton bootstrap copy."""
    candidates: list[str] = []
    if path:
        candidates.append(path)
    candidates.extend(FALLBACK_VIDEO_CANDIDATES)
    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if os.path.isfile(candidate):
            return candidate
    return None


def _without_live_only_tokens(command: list[str]) -> list[str]:
    """File loops cannot use the live HDMI shortcuts: they speed up or freeze."""
    cleaned: list[str] = []
    skip_value = False
    for token in command:
        if skip_value:
            skip_value = False
            continue
        if token == "leaky=downstream":
            continue
        if token in {"skip-vsync=true", "skip-vsync=false"}:
            continue
        if token == "skip-vsync":
            skip_value = True
            continue
        if token == "v4l2h264dec":
            cleaned.append("avdec_h264")
            continue
        if token == "sync=false":
            cleaned.append("sync=true")
            continue
        cleaned.append(token)
    return cleaned


def build_fallback_command(
    base: str | list[str] | None,
    settings_path: str | None,
    media_path: str | None,
) -> tuple[list[str], dict[str, Any]]:
    """Replace the live fdsrc with a looping local H.264 source on the same HDMI path."""
    command, profile = build_command(base, settings_path)
    if not media_path or not command or "fdsrc" not in command or "h264parse" not in command:
        return [], profile
    try:
        source_index = command.index("fdsrc")
    except ValueError:
        return [], profile
    decoder_index = next((index for index, token in enumerate(command) if token in {"v4l2h264dec", "avdec_h264"}), -1)
    if decoder_index < 0:
        try:
            decoder_index = command.index("h264parse", source_index)
        except ValueError:
            return [], profile
        decoder_index += 1
    source = [
        "filesrc", f"location={str(Path(media_path).resolve())}",
        "!", "qtdemux", "!", "h264parse", "config-interval=-1",
    ]
    fallback = command[:source_index] + source + ["!"] + command[decoder_index:]
                                                                        
                                                                  
    return _without_live_only_tokens(fallback), profile


def supervised_command(command: list[str], *, loop: bool, fallback: str | None = None) -> list[str]:
    """Use the same bounded DRM implementation in bootstrap and main releases."""
    if not command or "kmssink" not in command:
        return command
    executable = "gst-launch-1.0"
    if not os.access(executable, os.X_OK):
        executable = "gst-launch-1.0"
    if not os.access(executable, os.X_OK):
        raise FileNotFoundError("native HDMI player is missing from the image")
    pipeline = list(command)
    if Path(pipeline[0]).name == "gst-launch-1.0":
        pipeline.pop(0)
        while pipeline and pipeline[0] in {"-q", "-v", "-e", "--quiet", "--verbose"}:
            pipeline.pop(0)
                                                                           
                                                                               
                                                                 
    pipeline = [token for token in pipeline
                if not token.startswith("driver-name=") and not token.startswith("bus-id=")]
    mode = ["--loop"] if loop else (["--receiver", "--fallback", fallback] if fallback else [])
    return [executable, "--status", "/run/goggles-lab/hdmi-status.json", *mode, "--", *pipeline]
