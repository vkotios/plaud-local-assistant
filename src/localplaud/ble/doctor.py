"""Host doctor / readiness for experimental BLE Note Pro support."""

from __future__ import annotations

import os
import platform
import shutil
from typing import Any

from .bridge import (
    bluetooth_backend,
    bluetooth_supported,
    bridge_source_dir,
    find_rust_bridge,
    is_desktop_platform,
)
from .identity import identity_file_path, identity_permissions_ok, read_stored_identity
from .redact import identity_public_view


def ble_doctor_status(
    *,
    enabled: bool | None = None,
    identity_path: str | None = None,
    bridge_path: str | None = None,
) -> dict[str, Any]:
    """Return a redacted readiness report suitable for CLI / API / logs."""
    if enabled is None:
        try:
            from ..config import get_settings

            enabled = bool(get_settings().ble.enabled)
        except Exception:  # noqa: BLE001
            enabled = False

    identity_target = identity_file_path(identity_path)
    identity = read_stored_identity(identity_target)
    bridge = find_rust_bridge(bridge_path)
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    system = platform.system()
    wsl = bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"))

    notes: list[str] = []
    if not enabled:
        notes.append("BLE is feature-flagged off ([ble] enabled=false). Experimental.")
    if not is_desktop_platform():
        notes.append("BLE requires a desktop host (Windows / Linux / macOS).")
    if wsl:
        notes.append(
            "WSL: host Bluetooth passthrough is limited/unreliable; prefer native "
            "Windows WinRT bridge or a Linux host with BlueZ — full WSL BLE download "
            "is not an acceptance claim for this phase."
        )
    if system == "Windows":
        notes.append(
            "Windows path is experimental; OpenPlod documented WinRT build support "
            "but no verified Note Pro extraction on Windows hardware."
        )
    if system == "Linux" and not wsl:
        notes.append(
            "Linux BlueZ: discovery/connect verified upstream; full download not "
            "recorded upstream without a provisioned identity."
        )
    if bridge is None:
        notes.append(
            f"plaud-bridge binary not found. Build vendor/openplod-ble/plaud-bridge "
            f"(source at {bridge_source_dir()}) or set LOCALPLAUD_BLE__BRIDGE_PATH."
        )
    if identity is None:
        notes.append(
            "No plaud-device.json yet. Run: localplaud ble provision "
            "(paste tokenstr from web.plaud.ai)."
        )
    if ffmpeg is None or ffprobe is None:
        notes.append("ffmpeg/ffprobe recommended for decode/convert after BLE download.")

    return {
        "experimental": True,
        "enabled": enabled,
        "platform": system,
        "wsl": wsl,
        "desktop": is_desktop_platform(),
        "bluetoothBackend": bluetooth_backend(),
        "bridgePresent": bridge is not None,
        "bridgePath": str(bridge) if bridge else None,
        "bluetoothSupported": bluetooth_supported(bridge_path),
        "identityPath": str(identity_target),
        "identityPresent": identity is not None,
        "identityPermissionsOk": identity_permissions_ok(identity_target),
        "identity": identity_public_view(identity),
        "ffmpeg": ffmpeg is not None,
        "ffprobe": ffprobe is not None,
        "protocol": 20,
        "models": ["Note Pro (project 881/883)"],
        "notes": notes,
    }
