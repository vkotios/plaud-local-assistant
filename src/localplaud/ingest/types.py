"""Shared constants for ingest transports, providers, and policies."""

from __future__ import annotations

from typing import Literal

SourceTransport = Literal["cloud", "upload", "filesystem", "ble"]
ExternalProvider = Literal["plaud", "local", "ble", "filesystem"]
DedupeMode = Literal["off", "link", "reject_new"]
DedupeOutcome = Literal[
    "created",
    "reused",
    "linked_duplicate",
    "rejected_duplicate",
    "updated",
    "disabled",
]

# Stable BLE external-id shape reserved for Phase 4: ``{serial}:{sessionId}``.
BLE_EXTERNAL_ID_SEPARATOR = ":"

SOURCE_TRANSPORTS: frozenset[str] = frozenset({"cloud", "upload", "filesystem", "ble"})
EXTERNAL_PROVIDERS: frozenset[str] = frozenset({"plaud", "local", "ble", "filesystem"})


def ble_external_id(serial: str, session_id: str) -> str:
    """Build the Phase-4-ready BLE external id key."""
    serial_n = (serial or "").strip()
    session_n = (session_id or "").strip()
    if not serial_n or not session_n:
        raise ValueError("BLE external id requires both serial and session_id")
    if BLE_EXTERNAL_ID_SEPARATOR in serial_n:
        raise ValueError("BLE serial must not contain ':'")
    return f"{serial_n}{BLE_EXTERNAL_ID_SEPARATOR}{session_n}"


def parse_ble_external_id(value: str) -> tuple[str, str]:
    """Split a ``serial:sessionId`` key; raises ValueError if malformed."""
    serial, sep, session_id = (value or "").partition(BLE_EXTERNAL_ID_SEPARATOR)
    if not sep or not serial or not session_id or BLE_EXTERNAL_ID_SEPARATOR in session_id:
        raise ValueError("BLE external id must be serial:sessionId")
    return serial, session_id


def transport_for_origin(origin: str | None) -> SourceTransport:
    """Best-effort backfill mapping from legacy ``PlaudFile.origin``."""
    if origin == "local":
        return "upload"
    return "cloud"
