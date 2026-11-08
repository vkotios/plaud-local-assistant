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
    """Stub Bluetooth Note Pro backend — interface only (Phase 4).

    No OpenPlod protocol, crypto, or vendor modules are imported here.
    """

    name = "ble"

    def describe(self) -> dict:
        return {
            "name": self.name,
            "transport": "ble",
            "status": "stub",
            "notes": (
                "Interface reserved for Phase 4 OpenPlod-adapted adapter. "
                "External id shape: serial:sessionId. Not operational."
            ),
            "external_id_shape": "serial:sessionId",
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
        """Build a BLE-shaped candidate for orchestrator tests / future adapter."""
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
        raise NotImplementedError(
            "BLE ingest is a Phase 4 stub; no OpenPlod/protocol transfer is available"
        )


def list_backends() -> list[IngestBackend]:
    return [CloudBackend(), FilesystemBackend(), UploadBackend(), BleBackend()]
