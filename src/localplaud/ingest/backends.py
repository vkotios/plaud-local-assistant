"""Ingest backends: cloud poller, filesystem/upload, and stub BLE."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..config import Settings, get_settings
from .types import ExternalProvider, SourceTransport


@dataclass(frozen=True)
class BackendItem:
    """Normalized candidate produced by a backend before orchestrator ingest."""

    transport: SourceTransport
    provider: ExternalProvider
    external_id: str | None = None
    filename: str = ""
    audio_path: Path | None = None
    content_sha256: str | None = None
    audio_fingerprint: str | None = None
    filesize: int | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)
    ble_serial: str | None = None
    ble_session_id: str | None = None


class IngestBackend(Protocol):
    name: str

    def describe(self) -> dict: ...


class CloudBackend:
    """Wraps the official Plaud Open API / MCP poller path (no private APIs)."""

    name = "cloud"

    def describe(self) -> dict:
        return {
            "name": self.name,
            "transport": "cloud",
            "status": "available",
            "notes": "Uses sync_file_list / imports; official Open API or MCP only.",
        }

    def poll(self, settings: Settings | None = None) -> dict:
        from ..imports import check_plaud_now

        return check_plaud_now(settings or get_settings())


class FilesystemBackend:
    """Import audio already present on disk (folder/upload path)."""

    name = "filesystem"

    def describe(self) -> dict:
        return {
            "name": self.name,
            "transport": "filesystem",
            "status": "available",
            "notes": "Reads local paths; content-hash dedupe applies when enabled.",
        }

    def item_from_path(
        self,
        path: Path | str,
        *,
        filename: str | None = None,
        external_id: str | None = None,
        metadata: dict | None = None,
    ) -> BackendItem:
        audio_path = Path(path)
        if not audio_path.is_file():
            raise FileNotFoundError(f"audio path not found: {audio_path}")
        return BackendItem(
            transport="filesystem",
            provider="filesystem",
            external_id=external_id,
            filename=filename or audio_path.name,
            audio_path=audio_path,
            filesize=audio_path.stat().st_size,
            metadata=dict(metadata or {}),
        )


class UploadBackend:
    """HTTP/multipart upload path (bytes already written under download_dir)."""

    name = "upload"

    def describe(self) -> dict:
        return {
            "name": self.name,
            "transport": "upload",
            "status": "available",
            "notes": "Used by /api/imports/local/audio and orchestrated ingest.",
        }

    def item_from_path(
        self,
        path: Path | str,
        *,
        filename: str,
        external_id: str | None = None,
        filesize: int | None = None,
        duration_ms: int | None = None,
        metadata: dict | None = None,
    ) -> BackendItem:
        audio_path = Path(path)
        return BackendItem(
            transport="upload",
            provider="local",
            external_id=external_id,
            filename=filename,
            audio_path=audio_path,
            filesize=filesize if filesize is not None else (
                audio_path.stat().st_size if audio_path.is_file() else None
            ),
            duration_ms=duration_ms,
            metadata=dict(metadata or {}),
        )


class BleBackend:
    """Bluetooth Note Pro backend (Phase 4, experimental).

    Protocol/crypto/provision live in ``localplaud.ble`` (OpenPlod-adapted).
    Radio transfer needs a built ``plaud-bridge`` + ``plaud-device.json``.
    Decoded audio still ingests via ``item_from_session`` / orchestrator.
    """

    name = "ble"

    def describe(self) -> dict:
        enabled = False
        bridge_present = False
        identity_present = False
        try:
            from ..ble.doctor import ble_doctor_status
            from ..config import get_settings

            enabled = bool(get_settings().ble.enabled)
            report = ble_doctor_status(enabled=enabled)
            bridge_present = bool(report.get("bridgePresent"))
            identity_present = bool(report.get("identityPresent"))
        except Exception:  # noqa: BLE001 — describe must never raise
            pass
        if not enabled:
            status = "disabled"
            notes = (
                "Experimental OpenPlod-adapted BLE adapter present but feature-flagged "
                "off ([ble] enabled=false). External id: serial:sessionId."
            )
        elif bridge_present and identity_present:
            status = "experimental"
            notes = (
                "BLE enabled with identity + bridge; radio transfer remains experimental "
                "(protocol 20 / Note Pro). Prefer Linux acceptance; Windows path first."
            )
        else:
            status = "experimental"
            notes = (
                "BLE adapter modules available. Provision identity and build "
                "vendor/openplod-ble/plaud-bridge for radio ops. "
                "Decoded-audio ingest works without radio."
            )
        return {
            "name": self.name,
            "transport": "ble",
            "status": status,
            "notes": notes,
            "external_id_shape": "serial:sessionId",
            "enabled": enabled,
            "bridgePresent": bridge_present,
            "identityPresent": identity_present,
        }

    def item_from_session(
        self,
        *,
        serial: str,
        session_id: str,
        audio_path: Path | str | None = None,
        filename: str | None = None,
        metadata: dict | None = None,
    ) -> BackendItem:
        """Build a BLE-shaped candidate for orchestrator / adapter ingest."""
        path = Path(audio_path) if audio_path is not None else None
        return BackendItem(
            transport="ble",
            provider="ble",
            external_id=None,  # orchestrator builds serial:sessionId
            filename=filename or f"ble-{serial}-{session_id}",
            audio_path=path,
            filesize=path.stat().st_size if path is not None and path.is_file() else None,
            metadata=dict(metadata or {}),
            ble_serial=serial,
            ble_session_id=session_id,
        )

    def transfer(self, *_args, **_kwargs) -> None:
        from ..ble.service import transfer_not_available_reason

        reason = transfer_not_available_reason()
        if reason:
            raise NotImplementedError(reason)
        raise NotImplementedError(
            "Live BLE radio download is experimental; use provision + bridge doctor, "
            "then ingest decoded audio via BleBackend.item_from_session / "
            "localplaud.ble.service.ingest_decoded_session"
        )


def list_backends() -> list[IngestBackend]:
    return [CloudBackend(), FilesystemBackend(), UploadBackend(), BleBackend()]
