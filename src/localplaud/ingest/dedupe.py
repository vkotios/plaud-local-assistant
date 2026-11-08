"""Library-level duplicate detection (id + hash + optional fingerprint).

Safe default: link duplicates to an original row. Never delete or overwrite
existing audio or artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import PlaudFile, RecordingExternalId
from .types import DedupeMode, ExternalProvider, SourceTransport, ble_external_id


@dataclass(frozen=True)
class DedupeMatch:
    file_id: str
    reason: str  # external_id | content_sha256 | audio_fingerprint


@dataclass(frozen=True)
class DedupeDecision:
    action: str  # proceed | reuse | link | reject
    match: DedupeMatch | None = None
    reason: str | None = None


def resolve_duplicates(
    session: Session,
    *,
    workspace_id: int,
    mode: DedupeMode,
    provider: ExternalProvider | str | None,
    transport: SourceTransport | str | None,
    external_id: str | None,
    content_sha256: str | None,
    audio_fingerprint: str | None = None,
    ble_serial: str | None = None,
    ble_session_id: str | None = None,
) -> DedupeDecision:
    """Decide how to treat a candidate relative to the existing library.

    Priority:
    1. Exact external id (provider+transport+id, or BLE serial:sessionId)
    2. Content SHA-256
    3. Optional audio fingerprint (only when provided)
    """
    if mode == "off":
        return DedupeDecision(action="proceed", reason="dedupe_off")

    resolved_external = external_id
    resolved_provider = provider
    resolved_transport = transport
    if ble_serial and ble_session_id:
        resolved_external = ble_external_id(ble_serial, ble_session_id)
        resolved_provider = "ble"
        resolved_transport = "ble"

    if resolved_external and resolved_provider and resolved_transport:
        row = session.scalar(
            select(RecordingExternalId).where(
                RecordingExternalId.workspace_id == workspace_id,
                RecordingExternalId.provider == resolved_provider,
                RecordingExternalId.transport == resolved_transport,
                RecordingExternalId.external_id == resolved_external,
            )
        )
        if row is not None:
            return _matched(
                mode,
                DedupeMatch(file_id=row.file_id, reason="external_id"),
            )

    if content_sha256:
        # Prefer an original (no duplicate_of) when several share the hash.
        original = session.scalar(
            select(PlaudFile)
            .where(
                PlaudFile.workspace_id == workspace_id,
                PlaudFile.content_sha256 == content_sha256,
                PlaudFile.duplicate_of.is_(None),
            )
            .order_by(PlaudFile.created_at.asc())
        )
        if original is not None:
            return _matched(
                mode,
                DedupeMatch(file_id=original.id, reason="content_sha256"),
            )
        any_hash = session.scalar(
            select(PlaudFile)
            .where(
                PlaudFile.workspace_id == workspace_id,
                PlaudFile.content_sha256 == content_sha256,
            )
            .order_by(PlaudFile.created_at.asc())
        )
        if any_hash is not None:
            target = any_hash.duplicate_of or any_hash.id
            return _matched(
                mode,
                DedupeMatch(file_id=target, reason="content_sha256"),
            )

    if audio_fingerprint:
        original = session.scalar(
            select(PlaudFile)
            .where(
                PlaudFile.workspace_id == workspace_id,
                PlaudFile.audio_fingerprint == audio_fingerprint,
                PlaudFile.duplicate_of.is_(None),
            )
            .order_by(PlaudFile.created_at.asc())
        )
        if original is not None:
            return _matched(
                mode,
                DedupeMatch(file_id=original.id, reason="audio_fingerprint"),
            )

    return DedupeDecision(action="proceed", reason="no_match")


def _matched(mode: DedupeMode, match: DedupeMatch) -> DedupeDecision:
    if mode == "reject_new":
        return DedupeDecision(action="reject", match=match, reason=match.reason)
    if mode == "link":
        # Same external id → reuse the row (identity). Hash/fingerprint → link.
        if match.reason == "external_id":
            return DedupeDecision(action="reuse", match=match, reason=match.reason)
        return DedupeDecision(action="link", match=match, reason=match.reason)
    return DedupeDecision(action="proceed", match=match, reason="dedupe_off")


def register_external_id(
    session: Session,
    *,
    workspace_id: int,
    file_id: str,
    provider: str,
    transport: str,
    external_id: str,
) -> RecordingExternalId:
    """Idempotently attach an external id to a recording."""
    existing = session.scalar(
        select(RecordingExternalId).where(
            RecordingExternalId.workspace_id == workspace_id,
            RecordingExternalId.provider == provider,
            RecordingExternalId.transport == transport,
            RecordingExternalId.external_id == external_id,
        )
    )
    if existing is not None:
        return existing
    row = RecordingExternalId(
        workspace_id=workspace_id,
        file_id=file_id,
        provider=provider,
        transport=transport,
        external_id=external_id,
    )
    session.add(row)
    return row
