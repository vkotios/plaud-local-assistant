"""High-level experimental BLE service → Phase 3 ingest.

Does not pull OpenPlod vault/UI/transcription. Radio transfer requires a built
``plaud-bridge``; decoded-audio ingest works from fixtures or completed downloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ingest.backends import BleBackend
from ..ingest.orchestrator import IngestResult, candidate_from_backend_item, ingest_candidate
from .doctor import ble_doctor_status
from .identity import identity_file_path, read_stored_identity
from .provision import DEFAULT_PLAUD_DOMAIN, provision_device
from .redact import identity_public_view, redact_identifier, redact_serial
from .transport import (
    PlaudTransportError,
    run_bridge_doctor,
    scan_note_pros,
    scan_verbose_counts,
)


@dataclass(frozen=True)
class BleIngestRequest:
    serial: str
    session_id: str
    audio_path: Path
    filename: str | None = None
    metadata: dict | None = None


def status(*, enabled: bool | None = None) -> dict[str, Any]:
    report = ble_doctor_status(enabled=enabled)
    bridge_doctor = (
        run_bridge_doctor() if report.get("bridgePresent") else {"ok": False, "skipped": True}
    )
    # Never echo secrets from bridge doctor payloads.
    safe_bridge = {
        "ok": bridge_doctor.get("ok"),
        "skipped": bridge_doctor.get("skipped"),
        "returncode": bridge_doctor.get("returncode"),
    }
    report["bridgeDoctor"] = safe_bridge
    return report


def provision(
    *,
    token: str,
    serial: str,
    identifier: str,
    domain: str = DEFAULT_PLAUD_DOMAIN,
    identity_path: str | None = None,
) -> dict[str, Any]:
    identity = provision_device(
        token=token,
        serial=serial,
        identifier=identifier,
        domain=domain,
        identity_path=identity_path,
        write=True,
    )
    return {
        "ok": True,
        "identityPath": str(identity_file_path(identity_path)),
        "identity": identity_public_view(identity),
    }


def try_scan(*, timeout: float = 15.0) -> dict[str, Any]:
    """Best-effort BLE scan; returns redacted probe summaries."""
    try:
        probes = scan_note_pros(timeout=timeout)
    except PlaudTransportError as exc:
        return {"ok": False, "error": str(exc), "devices": []}
    devices = []
    for probe in probes:
        serial = probe.get("serial") or probe.get("sn")
        identifier = probe.get("identifier") or probe.get("address") or probe.get("id")
        devices.append(
            {
                "detected": bool(probe.get("detected")),
                "detail": probe.get("detail"),
                "serial": redact_serial(str(serial) if serial else None),
                "identifier": redact_identifier(str(identifier) if identifier else None),
                "name": probe.get("name"),
                "rssi": probe.get("rssi"),
                "protocolVersion": probe.get("protocolVersion") or probe.get("protocol"),
            }
        )
    detected = sum(1 for device in devices if device.get("detected"))
    return {
        "ok": True,
        "count": len(devices),
        "detected": detected,
        "devices": devices,
    }


def try_scan_verbose(*, seconds: float = 150.0) -> dict[str, Any]:
    """Filter-stage counts only (no MAC/serial). Safe for reports."""
    try:
        counts = scan_verbose_counts(seconds=seconds)
    except PlaudTransportError as exc:
        return {"ok": False, "error": str(exc)}
    # Drop any accidental identity fields if a future bridge adds them.
    safe = {
        key: value
        for key, value in counts.items()
        if key
        not in {
            "identifier",
            "serial",
            "address",
            "mac",
            "name",
            "manufacturerData",
        }
    }
    unique = int(safe.get("uniquePeripherals") or 0)
    accepted = int(safe.get("acceptedByFilter") or 0)
    safe["ok"] = True
    safe["rejectedByFilter"] = max(0, unique - accepted)
    return safe


def ingest_decoded_session(request: BleIngestRequest) -> IngestResult:
    """Feed already-decoded BLE audio into the Phase 3 orchestrator."""
    backend = BleBackend()
    item = backend.item_from_session(
        serial=request.serial,
        session_id=request.session_id,
        audio_path=request.audio_path,
        filename=request.filename,
        metadata={
            "sourceProvider": "plaud",
            "sourceTransport": "ble",
            **dict(request.metadata or {}),
        },
    )
    # transport=ble + ble_serial/session_id → orchestrator registers serial:sessionId.
    return ingest_candidate(candidate_from_backend_item(item))


def transfer_not_available_reason() -> str | None:
    identity = read_stored_identity()
    report = ble_doctor_status()
    if not report.get("enabled"):
        return "BLE feature flag is off ([ble] enabled=false)"
    if identity is None:
        return "No plaud-device.json; run localplaud ble provision first"
    if not report.get("bridgePresent"):
        return "plaud-bridge binary missing; build vendor/openplod-ble/plaud-bridge"
    return None
