"""Locate / describe the OpenPlod-adapted ``plaud-bridge`` BLE helper.

Adapted from OpenPlod ``src/sync/plaud-bridge.ts``
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).

The Rust crate lives under ``vendor/openplod-ble/plaud-bridge`` and must be
built separately (Rust toolchain). Without a built binary, scan/connect are
unavailable; provision still works with manual serial + identifier.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
from pathlib import Path

BLE_IDENTIFIER_PATTERN = re.compile(
    r"^(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}|[0-9a-f]{2}(?::[0-9a-f]{2}){5})$",
    re.IGNORECASE,
)

DESKTOP_PLATFORMS = frozenset({"Darwin", "Linux", "Windows"})

BLUETOOTH_BACKENDS = {
    "Darwin": "corebluetooth",
    "Linux": "bluez",
    "Windows": "winrt",
}

BRIDGE_BINARY = "plaud-bridge.exe" if os.name == "nt" else "plaud-bridge"


def is_bluetooth_identifier(value: str) -> bool:
    return bool(BLE_IDENTIFIER_PATTERN.match(value or ""))


def is_desktop_platform() -> bool:
    return platform.system() in DESKTOP_PLATFORMS


def bluetooth_backend() -> str | None:
    return BLUETOOTH_BACKENDS.get(platform.system())


def _repo_root() -> Path:
    # src/localplaud/ble/bridge.py → repo root
    return Path(__file__).resolve().parents[3]


def find_rust_bridge(explicit: str | Path | None = None) -> Path | None:
    """Return path to a built plaud-bridge binary, or None."""
    if explicit is not None:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for key in ("LOCALPLAUD_BLE__BRIDGE_PATH", "PLAUD_BLE_BRIDGE", "OPENPLOD_BLE_BRIDGE"):
        override = os.environ.get(key)
        if override:
            path = Path(override).expanduser()
            return path if path.is_file() else None
    which = shutil.which(BRIDGE_BINARY)
    if which:
        return Path(which)
    root = _repo_root()
    candidates = [
        root / "vendor" / "openplod-ble" / "plaud-bridge" / "target" / "release" / BRIDGE_BINARY,
        root / "vendor" / "openplod-ble" / "plaud-bridge" / "target" / "debug" / BRIDGE_BINARY,
        root / "bin" / BRIDGE_BINARY,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def bluetooth_supported(bridge_path: str | Path | None = None) -> bool:
    if not is_desktop_platform():
        return False
    return find_rust_bridge(bridge_path) is not None


def bridge_source_dir() -> Path:
    return _repo_root() / "vendor" / "openplod-ble" / "plaud-bridge"
