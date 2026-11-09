"""Redact BLE identity secrets from operator-facing status / logs."""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"


def redact_serial(serial: str | None) -> str | None:
    if not serial:
        return serial
    value = serial.strip()
    if len(value) <= 6:
        return REDACTED
    return f"{value[:3]}…{value[-2:]}"


def redact_identifier(identifier: str | None) -> str | None:
    if not identifier:
        return identifier
    value = identifier.strip()
    if len(value) <= 8:
        return REDACTED
    return f"{value[:5]}…{value[-2:]}"


def identity_public_view(identity: dict[str, Any] | None) -> dict[str, Any] | None:
    """Safe summary of a stored identity — never keys, tokens, or full serial."""
    if not identity:
        return None
    return {
        "authorized": True,
        "serial": redact_serial(str(identity.get("serial") or "")),
        "identifier": redact_identifier(str(identity.get("identifier") or "")),
        "deviceType": identity.get("deviceType"),
        "hasBindingToken": bool(identity.get("bindingToken")),
        "hasSignature": bool(identity.get("signature")),
        "hasPublicKey": bool(identity.get("publicKey")),
        "hasPrivateKey": bool(identity.get("privateKey")),
    }
