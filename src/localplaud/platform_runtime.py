"""Host / container runtime detection for packaging doctor checks.

Phase 6 packaging: default Docker images are **core only**. Bluetooth Note Pro
radio access requires a host BLE stack (BlueZ / WinRT / CoreBluetooth) and is
explicitly unsupported inside unprivileged containers. This module does not
implement BLE protocol or provision — those live in the experimental adapter.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def running_in_container() -> bool:
    """Best-effort container detection for doctor / operator messaging."""
    explicit = (os.environ.get("LOCALPLAUD_RUNTIME") or "").strip().lower()
    if explicit in {"docker", "container", "podman"}:
        return True
    if explicit in {"host", "native"}:
        return False
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return any(token in cgroup for token in ("docker", "containerd", "kubepods", "podman"))


def running_in_wsl() -> bool:
    return bool(os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"))


def ble_requested() -> bool:
    """True when the operator asked for BLE in this process environment.

    Reads only env / optional settings. Does not import the experimental BLE
    package (may be absent until Phase 4 merges).
    """
    raw = (os.environ.get("LOCALPLAUD_BLE__ENABLED") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    try:
        from .config import get_settings

        ble = getattr(get_settings(), "ble", None)
        if ble is not None:
            return bool(getattr(ble, "enabled", False))
    except Exception:  # noqa: BLE001 - packaging check must never crash doctor
        return False
    return False


def ble_packaging_status() -> dict[str, Any]:
    """Return a doctor-ready BLE packaging verdict for this runtime."""
    in_container = running_in_container()
    requested = ble_requested()
    wsl = running_in_wsl()
    docs = "docs/ble-host.md"

    if in_container and requested:
        return {
            "ok": False,
            "detail": (
                "BLE enabled inside a container is unsupported — use a Fedora/macOS "
                f"host with BlueZ/CoreBluetooth + plaud-bridge ({docs}); file import only here"
            ),
            "in_container": True,
            "requested": True,
            "wsl": wsl,
            "docs": docs,
        }
    if in_container:
        return {
            "ok": True,
            "detail": (
                f"core container (BLE radio not available; host path in {docs})"
            ),
            "in_container": True,
            "requested": False,
            "wsl": wsl,
            "docs": docs,
        }
    if wsl and requested:
        return {
            "ok": False,
            "detail": (
                "WSL Bluetooth passthrough is unreliable — prefer macOS or native "
                f"Linux+BlueZ for live Note Pro hardware ({docs})"
            ),
            "in_container": False,
            "requested": True,
            "wsl": True,
            "docs": docs,
        }
    if requested:
        return {
            "ok": True,
            "detail": (
                f"BLE requested on host — confirm BlueZ/D-Bus, plaud-bridge, ffmpeg ({docs}); "
                "experimental until hardware acceptance"
            ),
            "in_container": False,
            "requested": True,
            "wsl": False,
            "docs": docs,
        }
    return {
        "ok": True,
        "detail": f"not enabled (host BLE requirements: {docs})",
        "in_container": False,
        "requested": False,
        "wsl": wsl,
        "docs": docs,
    }
