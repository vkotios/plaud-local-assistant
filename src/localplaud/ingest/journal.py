"""Durable ingest job journal for interrupted import resume/retry safety."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db.models import IngestJob


def create_job(
    session: Session,
    *,
    workspace_id: int,
    backend: str,
    transport: str,
    content_sha256: str | None = None,
    external_key: str | None = None,
    detail: dict | None = None,
) -> IngestJob:
    job = IngestJob(
        id=str(uuid4()),
        workspace_id=workspace_id,
        backend=backend,
        transport=transport,
        status="running",
        content_sha256=content_sha256,
        external_key=external_key,
        detail=dict(detail or {}),
        started_at=datetime.now(UTC),
    )
    session.add(job)
    session.flush()
    return job


def complete_job(
    session: Session,
    job_id: str,
    *,
    file_id: str | None,
    outcome: str,
    detail: dict | None = None,
) -> None:
    job = session.get(IngestJob, job_id)
    if job is None:
        return
    job.status = "completed"
    job.file_id = file_id
    job.outcome = outcome
    if detail:
        merged = dict(job.detail or {})
        merged.update(detail)
        job.detail = merged
    job.completed_at = datetime.now(UTC)


def fail_job(session: Session, job_id: str, *, error: str) -> None:
    job = session.get(IngestJob, job_id)
    if job is None:
        return
    job.status = "failed"
    job.error = error[:2000]
    job.completed_at = datetime.now(UTC)


def find_resumable_job(
    session: Session,
    *,
    workspace_id: int,
    content_sha256: str | None,
    external_key: str | None,
) -> IngestJob | None:
    """Return a completed job for the same *external* identity.

    Resume is keyed by ``external_key`` only. Matching on content hash alone
    would collapse intentional ``link``-mode duplicate imports into a reuse.
    Content-hash duplicates are handled by ``resolve_duplicates``.
    """
    del content_sha256  # reserved for reject_new callers / future policy hooks
    if not external_key:
        return None
    return session.scalar(
        select(IngestJob)
        .where(
            IngestJob.workspace_id == workspace_id,
            IngestJob.external_key == external_key,
            IngestJob.status == "completed",
            IngestJob.file_id.is_not(None),
        )
        .order_by(IngestJob.completed_at.desc())
    )


def recover_interrupted_jobs() -> int:
    """Mark running/queued ingest jobs failed after process restart.

    Already-completed identities remain in the journal so a retry reuses the
    prior file_id instead of creating a second library row.
    """
    from ..db.session import session_scope

    with session_scope() as session:
        count = session.execute(
            update(IngestJob)
            .where(IngestJob.status.in_(("queued", "running")))
            .values(
                status="failed",
                error=(
                    "Ingest interrupted by application restart; retry the import; "
                    "completed identities will be reused via the ingest journal."
                ),
                completed_at=datetime.now(UTC),
            )
        ).rowcount
    return int(count or 0)
