"""Thin ingest status / orchestrated filesystem + BLE-stub API."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..ingest.orchestrator import (
    ingest_ble_stub,
    ingest_filesystem_path,
    ingest_status,
    poll_cloud,
    provenance_for_file,
)
from ..ingest.types import ble_external_id
from .upload_limits import MAX_UPLOAD_BYTES, UploadCleanupRoute

router = APIRouter(prefix="/api/ingest", tags=["ingest"])
_upload_router = APIRouter(route_class=UploadCleanupRoute)


class FilesystemIngestRequest(BaseModel):
    path: str
    filename: str | None = None
    external_id: str | None = None


class BleStubIngestRequest(BaseModel):
    serial: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    audio_path: str | None = None
    filename: str | None = None


@router.get("/status")
def get_ingest_status() -> dict:
    status = ingest_status()
    return {
        "enabled": status.enabled,
        "dedupe_mode": status.dedupe_mode,
        "hash_on_ingest": status.hash_on_ingest,
        "fingerprint_hook": status.fingerprint_hook,
        "backends": status.backends,
    }


@router.get("/files/{file_id}/provenance")
def get_file_provenance(file_id: str) -> dict:
    result = provenance_for_file(file_id)
    if result is None:
        raise HTTPException(status_code=404, detail="recording not found")
    return result


@router.post("/cloud/poll")
def post_cloud_poll() -> dict:
    from ..poller.poll import CatalogSyncBusy

    try:
        return poll_cloud()
    except CatalogSyncBusy:
        return {"new": 0, "queued": 0, "recordings": [], "busy": True}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail="Could not reach Plaud") from exc


@router.post("/filesystem")
def post_filesystem_ingest(body: FilesystemIngestRequest) -> dict:
    from ..config import get_settings

    if not get_settings().ingest.enabled:
        raise HTTPException(status_code=503, detail="ingest orchestrator disabled")
    try:
        result = ingest_filesystem_path(
            body.path, filename=body.filename, external_id=body.external_id
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _result_dict(result)


@router.post("/ble/stub")
def post_ble_stub_ingest(body: BleStubIngestRequest) -> dict:
    from ..config import get_settings

    if not get_settings().ingest.enabled:
        raise HTTPException(status_code=503, detail="ingest orchestrator disabled")
    try:
        ble_external_id(body.serial, body.session_id)
        result = ingest_ble_stub(
            serial=body.serial,
            session_id=body.session_id,
            audio_path=body.audio_path,
            filename=body.filename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    return _result_dict(result)


@_upload_router.post("/upload", status_code=201)
def post_orchestrated_upload(file: Annotated[UploadFile, File()]) -> dict:
    """Upload via orchestrator (dedupe-aware). Prefer this for Phase 3 clients."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from ..config import get_settings
    from ..ingest.orchestrator import ingest_upload_file
    from ..store.files import file_dir

    settings = get_settings()
    if not settings.ingest.enabled:
        raise HTTPException(status_code=503, detail="ingest orchestrator disabled")

    original_name = Path(file.filename or "audio").name
    extension = Path(original_name).suffix.lower().lstrip(".")
    if not extension:
        file.file.close()
        raise HTTPException(status_code=415, detail="unsupported audio/video format")

    staging_id = f"staging-{uuid4().hex}"
    destination = file_dir(staging_id) / f"audio.{extension}"
    written = 0
    result = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("wb") as output:
            while chunk := file.file.read(1 << 20):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="file exceeds 2 GB limit")
                output.write(chunk)
        if not written:
            raise HTTPException(status_code=422, detail="audio file is empty")
        result = ingest_upload_file(
            source_path=destination,
            filename=Path(original_name).stem or "Imported audio",
            filesize=written,
            metadata={
                "original_filename": original_name,
                "uploaded_at": datetime.now(UTC).isoformat(),
            },
            settings=settings,
            already_in_library_dir=False,
        )
        # Staging copy is leftover when the orchestrator reused/linked another row.
        if result.outcome in {"reused", "linked_duplicate", "rejected_duplicate"}:
            destination.unlink(missing_ok=True)
            with suppress(OSError):
                destination.parent.rmdir()
    except BaseException:
        with suppress(OSError):
            destination.unlink(missing_ok=True)
            destination.parent.rmdir()
        raise
    finally:
        file.file.close()
    assert result is not None
    return _result_dict(result)


def _result_dict(result) -> dict:
    return {
        "id": result.file_id,
        "outcome": result.outcome,
        "duplicate_of": result.duplicate_of,
        "content_sha256": result.content_sha256,
        "source_transport": result.source_transport,
        "dedupe_reason": result.dedupe_reason,
        "job_id": result.job_id,
        "detail": result.detail,
    }


router.include_router(_upload_router)
