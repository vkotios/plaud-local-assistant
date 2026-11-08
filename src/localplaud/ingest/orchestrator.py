"""Unified ingestion orchestrator over cloud, filesystem/upload, and BLE stub."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from shutil import copy2
from uuid import uuid4

from sqlalchemy import select

from ..config import Settings, get_settings
from ..db.models import FileStatus, PlaudFile
from ..db.session import session_scope
from ..db.tenancy import DEFAULT_WORKSPACE_ID, current_workspace_id
from ..store.files import file_dir
from . import journal
from .backends import (
    BackendItem,
    BleBackend,
    CloudBackend,
    FilesystemBackend,
    UploadBackend,
    list_backends,
)
from .dedupe import register_external_id, resolve_duplicates
from .hashing import content_sha256_of_path, optional_fingerprint_stub
from .types import DedupeOutcome, ExternalProvider, SourceTransport, ble_external_id


@dataclass
class IngestCandidate:
    transport: SourceTransport
    provider: ExternalProvider
    filename: str
    audio_path: Path | None = None
    external_id: str | None = None
    content_sha256: str | None = None
    audio_fingerprint: str | None = None
    filesize: int | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)
    ble_serial: str | None = None
    ble_session_id: str | None = None
    copy_audio: bool = True


@dataclass(frozen=True)
class IngestResult:
    file_id: str | None
    outcome: DedupeOutcome
    duplicate_of: str | None = None
    content_sha256: str | None = None
    source_transport: str | None = None
    dedupe_reason: str | None = None
    job_id: str | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IngestStatus:
    enabled: bool
    dedupe_mode: str
    hash_on_ingest: bool
    fingerprint_hook: bool
    backends: list[dict]


def ingest_status(settings: Settings | None = None) -> IngestStatus:
    settings = settings or get_settings()
    cfg = settings.ingest
    return IngestStatus(
        enabled=cfg.enabled,
        dedupe_mode=cfg.dedupe_mode,
        hash_on_ingest=cfg.hash_on_ingest,
        fingerprint_hook=cfg.fingerprint_hook,
        backends=[backend.describe() for backend in list_backends()],
    )


def candidate_from_backend_item(item: BackendItem, *, copy_audio: bool = True) -> IngestCandidate:
    return IngestCandidate(
        transport=item.transport,
        provider=item.provider,
        filename=item.filename,
        audio_path=item.audio_path,
        external_id=item.external_id,
        content_sha256=item.content_sha256,
        audio_fingerprint=item.audio_fingerprint,
        filesize=item.filesize,
        duration_ms=item.duration_ms,
        metadata=dict(item.metadata),
        ble_serial=item.ble_serial,
        ble_session_id=item.ble_session_id,
        copy_audio=copy_audio,
    )


def ingest_candidate(
    candidate: IngestCandidate,
    settings: Settings | None = None,
) -> IngestResult:
    """Ingest one candidate through dedupe + provenance registration.

    Safe defaults: never delete existing rows; ``dedupe_mode=link`` creates a
    linked duplicate row that points at the original via ``duplicate_of``.
    """
    settings = settings or get_settings()
    cfg = settings.ingest
    if not cfg.enabled:
        return IngestResult(
            file_id=None,
            outcome="disabled",
            source_transport=candidate.transport,
            detail={"reason": "ingest.enabled is false; use poller/upload paths directly"},
        )

    workspace_id = current_workspace_id() or DEFAULT_WORKSPACE_ID
    digest = candidate.content_sha256
    if digest is None and cfg.hash_on_ingest and candidate.audio_path is not None:
        digest = content_sha256_of_path(candidate.audio_path)

    fingerprint = candidate.audio_fingerprint
    if fingerprint is None:
        fingerprint = optional_fingerprint_stub(
            content_sha256=digest, enabled=cfg.fingerprint_hook
        )

    external_key = _external_key(candidate)
    with session_scope() as session:
        prior = journal.find_resumable_job(
            session,
            workspace_id=workspace_id,
            content_sha256=digest,
            external_key=external_key,
        )
        if prior is not None and prior.file_id:
            existing = session.get(PlaudFile, prior.file_id)
            if existing is not None:
                return IngestResult(
                    file_id=existing.id,
                    outcome="reused",
                    duplicate_of=existing.duplicate_of,
                    content_sha256=existing.content_sha256 or digest,
                    source_transport=existing.source_transport or candidate.transport,
                    dedupe_reason="ingest_journal",
                    job_id=prior.id,
                    detail={"resumed": True},
                )

        job = journal.create_job(
            session,
            workspace_id=workspace_id,
            backend=candidate.provider,
            transport=candidate.transport,
            content_sha256=digest,
            external_key=external_key,
            detail={"filename": candidate.filename},
        )
        job_id = job.id

        decision = resolve_duplicates(
            session,
            workspace_id=workspace_id,
            mode=cfg.dedupe_mode,
            provider=candidate.provider,
            transport=candidate.transport,
            external_id=candidate.external_id,
            content_sha256=digest,
            audio_fingerprint=fingerprint,
            ble_serial=candidate.ble_serial,
            ble_session_id=candidate.ble_session_id,
        )

        if decision.action == "reuse" and decision.match is not None:
            file_id = decision.match.file_id
            _ensure_provenance(
                session,
                workspace_id=workspace_id,
                file_id=file_id,
                candidate=candidate,
                digest=digest,
                fingerprint=fingerprint,
            )
            journal.complete_job(
                session,
                job_id,
                file_id=file_id,
                outcome="reused",
                detail={"dedupe_reason": decision.reason},
            )
            return IngestResult(
                file_id=file_id,
                outcome="reused",
                content_sha256=digest,
                source_transport=candidate.transport,
                dedupe_reason=decision.reason,
                job_id=job_id,
            )

        if decision.action == "reject" and decision.match is not None:
            journal.complete_job(
                session,
                job_id,
                file_id=decision.match.file_id,
                outcome="rejected_duplicate",
                detail={"dedupe_reason": decision.reason},
            )
            return IngestResult(
                file_id=decision.match.file_id,
                outcome="rejected_duplicate",
                duplicate_of=decision.match.file_id,
                content_sha256=digest,
                source_transport=candidate.transport,
                dedupe_reason=decision.reason,
                job_id=job_id,
            )

        duplicate_of = (
            decision.match.file_id if decision.action == "link" and decision.match else None
        )
        try:
            file_id, stored_path = _materialize_row(
                session,
                workspace_id=workspace_id,
                candidate=candidate,
                digest=digest,
                fingerprint=fingerprint,
                duplicate_of=duplicate_of,
            )
        except Exception as exc:  # noqa: BLE001 - surface as failed journal entry
            journal.fail_job(session, job_id, error=str(exc))
            raise

        outcome: DedupeOutcome = (
            "linked_duplicate" if duplicate_of is not None else "created"
        )
        journal.complete_job(
            session,
            job_id,
            file_id=file_id,
            outcome=outcome,
            detail={
                "dedupe_reason": decision.reason,
                "audio_path": str(stored_path) if stored_path else None,
            },
        )
        return IngestResult(
            file_id=file_id,
            outcome=outcome,
            duplicate_of=duplicate_of,
            content_sha256=digest,
            source_transport=candidate.transport,
            dedupe_reason=decision.reason,
            job_id=job_id,
            detail={"audio_path": str(stored_path) if stored_path else None},
        )


def ingest_upload_file(
    *,
    source_path: Path,
    filename: str,
    filesize: int | None = None,
    duration_ms: int | None = None,
    metadata: dict | None = None,
    settings: Settings | None = None,
    already_in_library_dir: bool = False,
) -> IngestResult:
    """Convenience path used by the local upload API."""
    backend = UploadBackend()
    item = backend.item_from_path(
        source_path,
        filename=filename,
        filesize=filesize,
        duration_ms=duration_ms,
        metadata=metadata,
    )
    return ingest_candidate(
        candidate_from_backend_item(item, copy_audio=not already_in_library_dir),
        settings=settings,
    )


def ingest_filesystem_path(
    path: Path | str,
    *,
    filename: str | None = None,
    external_id: str | None = None,
    metadata: dict | None = None,
    settings: Settings | None = None,
) -> IngestResult:
    backend = FilesystemBackend()
    item = backend.item_from_path(
        path, filename=filename, external_id=external_id, metadata=metadata
    )
    return ingest_candidate(candidate_from_backend_item(item), settings=settings)


def ingest_ble_stub(
    *,
    serial: str,
    session_id: str,
    audio_path: Path | str | None = None,
    filename: str | None = None,
    metadata: dict | None = None,
    settings: Settings | None = None,
) -> IngestResult:
    """Accept a BLE-shaped candidate without performing any BLE transfer."""
    backend = BleBackend()
    item = backend.item_from_session(
        serial=serial,
        session_id=session_id,
        audio_path=audio_path,
        filename=filename,
        metadata=metadata,
    )
    return ingest_candidate(candidate_from_backend_item(item), settings=settings)


def poll_cloud(settings: Settings | None = None) -> dict:
    """Cloud backend entry: incremental official catalog check."""
    return CloudBackend().poll(settings)


def recover_interrupted_ingest_jobs() -> int:
    return journal.recover_interrupted_jobs()


def annotate_existing_file(
    session,
    *,
    file_id: str,
    transport: SourceTransport,
    provider: ExternalProvider | str,
    external_id: str | None,
    content_sha256: str | None = None,
    audio_fingerprint: str | None = None,
) -> None:
    """Attach Phase 3 provenance to a row created by legacy poller/upload paths."""
    row = session.get(PlaudFile, file_id)
    if row is None:
        return
    if row.source_transport is None:
        row.source_transport = transport
    if content_sha256 and not row.content_sha256:
        row.content_sha256 = content_sha256
    if audio_fingerprint and not row.audio_fingerprint:
        row.audio_fingerprint = audio_fingerprint
    if external_id:
        register_external_id(
            session,
            workspace_id=row.workspace_id,
            file_id=file_id,
            provider=provider,
            transport=transport,
            external_id=external_id,
        )


def _external_key(candidate: IngestCandidate) -> str | None:
    if candidate.ble_serial and candidate.ble_session_id:
        return f"ble:{ble_external_id(candidate.ble_serial, candidate.ble_session_id)}"
    if candidate.external_id:
        return f"{candidate.provider}:{candidate.transport}:{candidate.external_id}"
    return None


def _ensure_provenance(
    session,
    *,
    workspace_id: int,
    file_id: str,
    candidate: IngestCandidate,
    digest: str | None,
    fingerprint: str | None,
) -> None:
    row = session.get(PlaudFile, file_id)
    if row is None:
        return
    if row.source_transport is None:
        row.source_transport = candidate.transport
    if digest and not row.content_sha256:
        row.content_sha256 = digest
    if fingerprint and not row.audio_fingerprint:
        row.audio_fingerprint = fingerprint
    external_id = candidate.external_id
    provider = candidate.provider
    transport = candidate.transport
    if candidate.ble_serial and candidate.ble_session_id:
        external_id = ble_external_id(candidate.ble_serial, candidate.ble_session_id)
        provider = "ble"
        transport = "ble"
    if external_id:
        register_external_id(
            session,
            workspace_id=workspace_id,
            file_id=file_id,
            provider=provider,
            transport=transport,
            external_id=external_id,
        )


def _materialize_row(
    session,
    *,
    workspace_id: int,
    candidate: IngestCandidate,
    digest: str | None,
    fingerprint: str | None,
    duplicate_of: str | None,
) -> tuple[str, Path | None]:
    file_id = _allocate_file_id(candidate)
    dest: Path | None = None
    if candidate.audio_path is not None:
        source = Path(candidate.audio_path)
        extension = source.suffix.lstrip(".") or "bin"
        dest = file_dir(file_id) / f"audio.{extension}"
        if candidate.copy_audio:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != dest.resolve():
                copy2(source, dest)
        else:
            # Caller already wrote into the library directory (upload API).
            dest = source
            dest.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC)
    filename = Path(candidate.filename).stem or candidate.filename or file_id
    fullname = candidate.filename or (dest.name if dest else filename)
    filesize = candidate.filesize
    if filesize is None and dest is not None and dest.is_file():
        filesize = dest.stat().st_size

    raw = {
        "origin": candidate.provider,
        "source_transport": candidate.transport,
        "ingest": "orchestrator",
        **dict(candidate.metadata or {}),
    }
    if candidate.ble_serial and candidate.ble_session_id:
        raw["ble_serial"] = candidate.ble_serial
        raw["ble_session_id"] = candidate.ble_session_id
        raw["ble_external_id"] = ble_external_id(
            candidate.ble_serial, candidate.ble_session_id
        )

    origin = "plaud" if candidate.transport == "cloud" else "local"
    session.add(
        PlaudFile(
            id=file_id,
            workspace_id=workspace_id,
            filename=filename,
            fullname=fullname,
            filesize=filesize,
            duration_ms=candidate.duration_ms,
            start_time_ms=int(now.timestamp() * 1000),
            status=FileStatus.downloaded if dest is not None else FileStatus.metadata_only,
            audio_path=str(dest) if dest is not None else None,
            downloaded_at=now if dest is not None else None,
            origin=origin,
            source_transport=candidate.transport,
            content_sha256=digest,
            audio_fingerprint=fingerprint,
            duplicate_of=duplicate_of,
            dedupe_status=(
                "linked_duplicate" if duplicate_of is not None else "original"
            ),
            raw=raw,
        )
    )
    session.flush()

    external_id = candidate.external_id
    provider = candidate.provider
    transport = candidate.transport
    if candidate.ble_serial and candidate.ble_session_id:
        external_id = ble_external_id(candidate.ble_serial, candidate.ble_session_id)
        provider = "ble"
        transport = "ble"
    if external_id:
        register_external_id(
            session,
            workspace_id=workspace_id,
            file_id=file_id,
            provider=provider,
            transport=transport,
            external_id=external_id,
        )
    return file_id, dest


def _allocate_file_id(candidate: IngestCandidate) -> str:
    if candidate.transport == "cloud" and candidate.external_id:
        return candidate.external_id
    if candidate.ble_serial and candidate.ble_session_id:
        # Local library id stays opaque; BLE identity lives in external_ids.
        return f"ble-{uuid4().hex}"
    return f"local-{uuid4().hex}"


def provenance_for_file(file_id: str) -> dict | None:
    """Return transport + external ids for a recording (thin query helper)."""
    from ..db.models import RecordingExternalId

    with session_scope() as session:
        row = session.get(PlaudFile, file_id)
        if row is None:
            return None
        ids = session.scalars(
            select(RecordingExternalId).where(RecordingExternalId.file_id == file_id)
        ).all()
        return {
            "id": row.id,
            "origin": row.origin,
            "source_transport": row.source_transport,
            "content_sha256": row.content_sha256,
            "audio_fingerprint": row.audio_fingerprint,
            "duplicate_of": row.duplicate_of,
            "dedupe_status": row.dedupe_status,
            "external_ids": [
                {
                    "provider": item.provider,
                    "transport": item.transport,
                    "external_id": item.external_id,
                }
                for item in ids
            ],
        }
