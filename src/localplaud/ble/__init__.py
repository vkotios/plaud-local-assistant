"""Experimental Bluetooth Note Pro adapter (OpenPlod-adapted, MIT).

Isolated from localplaud vault/UI/transcription. Feature-flagged via
``[ble] enabled``. Protocol 20 / Note Pro only. See ``docs/ble.md``.
"""

from __future__ import annotations

from .doctor import ble_doctor_status
from .identity import (
    clear_stored_identity,
    identity_file_path,
    read_stored_identity,
    write_stored_identity,
)
from .provision import (
    DEFAULT_PLAUD_DOMAIN,
    PLAUD_DOMAINS,
    PlaudIdentityProvisioner,
    device_type_for_serial,
    normalize_access_token,
    parse_access_token,
    provision_device,
)

__all__ = [
    "DEFAULT_PLAUD_DOMAIN",
    "PLAUD_DOMAINS",
    "PlaudIdentityProvisioner",
    "ble_doctor_status",
    "clear_stored_identity",
    "device_type_for_serial",
    "identity_file_path",
    "normalize_access_token",
    "parse_access_token",
    "provision_device",
    "read_stored_identity",
    "write_stored_identity",
]
