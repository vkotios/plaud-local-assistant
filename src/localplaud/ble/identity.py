"""On-disk ``plaud-device.json`` identity storage (OpenPlod-adapted).

Adapted from OpenPlod ``src/sync/plaud-provision.ts`` identity helpers
(MIT, Copyright 2026 Remi Pelloux and OpenPlod contributors).
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any, TypedDict


class PlaudDeviceIdentity(TypedDict, total=False):
    identifier: str
    serial: str
    bindingToken: str
    signature: str
    publicKey: str
    privateKey: str
    deviceType: str


REQUIRED_IDENTITY_FIELDS = (
    "identifier",
    "serial",
    "bindingToken",
    "signature",
    "publicKey",
    "privateKey",
)


def default_identity_directory() -> Path:
    """Directory that holds ``plaud-device.json`` beside local library data."""
    override = os.environ.get("LOCALPLAUD_LIBRARY_PATH") or os.environ.get(
        "OPENPLOD_LIBRARY_PATH"
    )
    if override:
        return Path(override).expanduser().resolve().parent
    return Path("data").resolve()


def identity_file_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    for key in ("LOCALPLAUD_BLE__IDENTITY_PATH", "PLAUD_DEVICE_IDENTITY", "OPENPLOD_DEVICE_IDENTITY"):
        value = os.environ.get(key)
        if value:
            return Path(value).expanduser().resolve()
    return default_identity_directory() / "plaud-device.json"


def read_stored_identity(path: str | Path | None = None) -> PlaudDeviceIdentity | None:
    target = identity_file_path(path)
    try:
        parsed = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed  # type: ignore[return-value]


def validate_identity(identity: dict[str, Any]) -> PlaudDeviceIdentity:
    missing = [field for field in REQUIRED_IDENTITY_FIELDS if not identity.get(field)]
    if missing:
        raise ValueError(f"Identity is missing required fields: {', '.join(missing)}")
    return identity  # type: ignore[return-value]


def write_stored_identity(
    identity: dict[str, Any],
    path: str | Path | None = None,
) -> Path:
    """Persist identity with owner-only permissions where the OS allows."""
    validated = validate_identity(identity)
    target = identity_file_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(target.parent, 0o700)
        except OSError:
            pass
    payload = f"{json.dumps(validated, indent=2, ensure_ascii=False)}\n"
    # Write privately when possible (POSIX). Windows ACLs differ; still avoid
    # world-readable defaults by opening with restrictive mode flags.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(target), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
    except Exception:
        with suppress(OSError):
            os.close(fd)
        raise
    if os.name != "nt":
        with suppress(OSError):
            os.chmod(target, 0o600)
    return target


def clear_stored_identity(path: str | Path | None = None) -> bool:
    target = identity_file_path(path)
    if not target.exists():
        return False
    target.unlink(missing_ok=True)
    return True


def identity_permissions_ok(path: str | Path | None = None) -> bool | None:
    """Return True/False on POSIX; None on Windows (ACLs not checked here)."""
    if os.name == "nt":
        return None
    target = identity_file_path(path)
    if not target.exists():
        return None
    mode = target.stat().st_mode
    return (mode & (stat.S_IRWXG | stat.S_IRWXO)) == 0
