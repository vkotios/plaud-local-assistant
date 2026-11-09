"""Read-only local knowledge library tools (no MCP transport dependency).

Wraps localplaud search, Ask, export, and ingest provenance helpers. Destructive
or mutate operations are intentionally absent in v1.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import func, or_, select

from localplaud.db.models import Folder, PlaudFile, Tag
from localplaud.db.session import session_scope
from localplaud.export_formats import (
    MissingExportContentError,
    recording_data,
    render_notes,
    render_transcript,
    transcript_provenance,
)
from localplaud.ingest.orchestrator import provenance_for_file
from localplaud.library_search import lexical_search

READ_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "knowledge_search",
        "knowledge_ask",
        "knowledge_list_recordings",
        "knowledge_list_folders",
        "knowledge_list_tags",
        "knowledge_get_recording",
        "knowledge_get_transcript",
        "knowledge_get_notes",
        "knowledge_get_provenance",
    }
)

_FILE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_MAX_LIST = 50
_MAX_SEARCH = 50
_MAX_CHARS_CAP = 30_000
_MIN_CHARS = 1_000


class KnowledgeToolError(ValueError):
    """User-facing tool argument or lookup error."""


def _file_id(value: str) -> str:
    value = (value or "").strip()
    if not _FILE_ID_RE.fullmatch(value):
        raise KnowledgeToolError("Provide a valid recording ID")
    return value


def _require_active_recording(file_id: str) -> str:
    """Validate file_id and refuse missing or trashed recordings."""
    file_id = _file_id(file_id)
    with session_scope() as session:
        row = session.get(PlaudFile, file_id)
        if row is None or row.is_trash:
            raise KnowledgeToolError("recording not found")
    return file_id


def _clamp_max_chars(max_chars: int) -> int:
    return max(_MIN_CHARS, min(int(max_chars), _MAX_CHARS_CAP))


def _paginate(text: str, *, max_chars: int, offset: int) -> dict[str, Any]:
    max_chars = _clamp_max_chars(max_chars)
    if offset < 0 or offset > len(text):
        raise KnowledgeToolError("offset must be within the document's total_chars")
    end = min(offset + max_chars, len(text))
    return {
        "offset": offset,
        "next_offset": end if end < len(text) else None,
        "end_of_document": end >= len(text),
        "total_chars": len(text),
        "max_chars": max_chars,
        "content": text[offset:end],
    }


def _public_source(hit: dict) -> dict:
    return {
        key: hit.get(key)
        for key in (
            "file_id",
            "filename",
            "kind",
            "text",
            "start",
            "end",
            "speaker",
            "speaker_key",
            "score",
            "target",
            "artifact_id",
        )
        if key in hit
    }


def knowledge_search(
    query: str,
    *,
    folder_id: int | None = None,
    tag_id: int | None = None,
    origin: str | None = None,
    limit: int = 20,
    semantic: bool = False,
) -> dict[str, Any]:
    """Lexical (default) library search; optional semantic retrieve when indexed."""
    query = (query or "").strip()
    if not query:
        raise KnowledgeToolError("query must not be empty")
    limit = max(1, min(int(limit), _MAX_SEARCH))
    if origin not in (None, "", "plaud", "local"):
        raise KnowledgeToolError("origin must be 'plaud', 'local', or omitted")
    origin_filter = origin if origin in {"plaud", "local"} else None
    hits = lexical_search(
        query,
        folder_id=folder_id,
        tag_id=tag_id,
        origin=origin_filter,
        limit=limit,
    )
    semantic_hits: list[dict] = []
    if semantic:
        try:
            from localplaud.worker.qa import retrieve

            scope = {
                key: value
                for key, value in {
                    "folder_id": folder_id,
                    "tag_id": tag_id,
                    "origin": origin_filter,
                }.items()
                if value is not None
            }
            semantic_hits = retrieve(
                query,
                top_k=min(limit, 30),
                retrieval_scope=scope or None,
            )
        except Exception:  # noqa: BLE001 — embeddings/provider may be unavailable
            semantic_hits = []
    return {
        "query": query,
        "count": len(hits),
        "hits": [_public_source(hit) for hit in hits[:limit]],
        "semantic_count": len(semantic_hits),
        "semantic_hits": [_public_source(hit) for hit in semantic_hits[:limit]],
        "cloud_credentials_required": False,
    }


def knowledge_ask(
    question: str,
    *,
    file_id: str | None = None,
    top_k: int = 6,
) -> dict[str, Any]:
    """Grounded Ask over one recording or the whole library.

    Uses the app's configured embed/Ask profile (may egress if cloud/remote is
    opted in). Never calls Plaud cloud. May write non-destructive
    ``provider_cost_reservations`` accounting rows — same as Web Ask.
    """
    question = (question or "").strip()
    if not question:
        raise KnowledgeToolError("question must not be empty")
    top_k = max(1, min(int(top_k), 12))
    scoped_id = _require_active_recording(file_id) if file_id is not None else None
    from localplaud.worker.qa import answer

    result = answer(question, top_k=top_k, file_id=scoped_id)
    sources = [_public_source(hit) for hit in result.get("sources") or []]
    provenance = result.get("provenance") or {}
    return {
        "answer": result.get("answer", ""),
        "sources": sources,
        "file_id": scoped_id,
        "provenance": {
            "provider": provenance.get("provider"),
            "model": provenance.get("model"),
            "profile": provenance.get("profile"),
        },
        "cloud_credentials_required": False,
        "side_effects": ["provider_cost_reservations"],
    }


def knowledge_list_recordings(
    *,
    query: str = "",
    origin: str | None = None,
    folder_id: int | None = None,
    tag_id: int | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """List bounded recording metadata from the local library (no audio)."""
    max_results = max(1, min(int(max_results), _MAX_LIST))
    needle = (query or "").strip().casefold()
    if origin not in (None, "", "plaud", "local"):
        raise KnowledgeToolError("origin must be 'plaud', 'local', or omitted")
    with session_scope() as session:
        stmt = select(PlaudFile).where(PlaudFile.is_trash.is_(False))
        if folder_id is not None:
            stmt = stmt.where(PlaudFile.folder_id == folder_id)
        if tag_id is not None:
            stmt = stmt.where(PlaudFile.tags.any(Tag.id == tag_id))
        if origin == "plaud":
            stmt = stmt.where(or_(PlaudFile.origin == "plaud", PlaudFile.origin.is_(None)))
        elif origin == "local":
            stmt = stmt.where(PlaudFile.origin == "local")
        rows = list(
            session.scalars(stmt.order_by(PlaudFile.start_time_ms.desc().nullslast(), PlaudFile.id))
        )
        files: list[dict[str, Any]] = []
        for row in rows:
            title = row.display_title
            if needle and needle not in title.casefold() and needle not in (row.filename or "").casefold():
                continue
            files.append(
                {
                    "id": row.id,
                    "title": title,
                    "filename": row.filename,
                    "origin": row.origin,
                    "source_transport": row.source_transport,
                    "folder_id": row.folder_id,
                    "start_time_ms": row.start_time_ms,
                    "duration_ms": row.duration_ms,
                    "dedupe_status": row.dedupe_status,
                    "duplicate_of": row.duplicate_of,
                }
            )
            if len(files) >= max_results:
                break
    return {
        "count": len(files),
        "returned": len(files),
        "files": files,
        "cloud_credentials_required": False,
    }


def knowledge_list_folders() -> dict[str, Any]:
    with session_scope() as session:
        folders = list(session.scalars(select(Folder).order_by(func.lower(Folder.name), Folder.id)))
        counts = dict(
            session.execute(
                select(PlaudFile.folder_id, func.count(PlaudFile.id))
                .where(PlaudFile.is_trash.is_(False), PlaudFile.folder_id.is_not(None))
                .group_by(PlaudFile.folder_id)
            ).all()
        )
        return {
            "folders": [
                {
                    "id": row.id,
                    "name": row.name,
                    "color": row.color,
                    "count": counts.get(row.id, 0),
                }
                for row in folders
            ],
            "cloud_credentials_required": False,
        }


def knowledge_list_tags() -> dict[str, Any]:
    from localplaud.db.models import recording_tags

    with session_scope() as session:
        tags = list(session.scalars(select(Tag).order_by(func.lower(Tag.name), Tag.id)))
        counts = dict(
            session.execute(
                select(recording_tags.c.tag_id, func.count(recording_tags.c.file_id))
                .join(PlaudFile, PlaudFile.id == recording_tags.c.file_id)
                .where(PlaudFile.is_trash.is_(False))
                .group_by(recording_tags.c.tag_id)
            ).all()
        )
        return {
            "tags": [
                {
                    "id": row.id,
                    "name": row.name,
                    "color": row.color,
                    "kind": row.kind,
                    "count": counts.get(row.id, 0),
                }
                for row in tags
            ],
            "cloud_credentials_required": False,
        }


def knowledge_get_recording(file_id: str) -> dict[str, Any]:
    """Return one recording's library metadata plus ingest provenance."""
    file_id = _require_active_recording(file_id)
    with session_scope() as session:
        row = session.get(PlaudFile, file_id)
        assert row is not None  # validated above
        tag_names = [tag.name for tag in row.tags]
        folder_name = row.folder.name if row.folder is not None else None
        meta = {
            "id": row.id,
            "title": row.display_title,
            "filename": row.filename,
            "origin": row.origin,
            "source_transport": row.source_transport,
            "folder_id": row.folder_id,
            "folder_name": folder_name,
            "tags": tag_names,
            "start_time_ms": row.start_time_ms,
            "duration_ms": row.duration_ms,
            "content_sha256": row.content_sha256,
            "dedupe_status": row.dedupe_status,
            "duplicate_of": row.duplicate_of,
        }
    ingest = provenance_for_file(file_id) or {}
    try:
        data = recording_data(file_id)
        has_transcript = bool(data.get("segments"))
        has_notes = bool(data.get("notes"))
        transcript_lineage = data.get("transcript_provenance") or {}
    except Exception:  # noqa: BLE001
        has_transcript = False
        has_notes = False
        transcript_lineage = {}
    return {
        "recording": meta,
        "ingest_provenance": ingest,
        "has_transcript": has_transcript,
        "has_notes": has_notes,
        "transcript_provenance": transcript_lineage,
        "cloud_credentials_required": False,
    }


def knowledge_get_transcript(
    file_id: str,
    *,
    max_chars: int = 16_000,
    offset: int = 0,
    timestamps: bool = True,
    speakers: bool = True,
) -> dict[str, Any]:
    file_id = _require_active_recording(file_id)
    try:
        payload, _media = render_transcript(
            file_id, "txt", timestamps=timestamps, speakers=speakers
        )
    except MissingExportContentError as exc:
        raise KnowledgeToolError(str(exc)) from exc
    text = payload.decode("utf-8", errors="replace")
    page = _paginate(text, max_chars=max_chars, offset=offset)
    return {
        "file_id": file_id,
        "format": "txt",
        **page,
        "cloud_credentials_required": False,
    }


def knowledge_get_notes(
    file_id: str,
    *,
    max_chars: int = 16_000,
    offset: int = 0,
) -> dict[str, Any]:
    file_id = _require_active_recording(file_id)
    try:
        payload, _media = render_notes(file_id, "md")
    except MissingExportContentError as exc:
        raise KnowledgeToolError(str(exc)) from exc
    text = payload.decode("utf-8", errors="replace")
    page = _paginate(text, max_chars=max_chars, offset=offset)
    return {
        "file_id": file_id,
        "format": "md",
        **page,
        "cloud_credentials_required": False,
    }


def knowledge_get_provenance(file_id: str) -> dict[str, Any]:
    """Combine ingest transport provenance with canonical transcript lineage."""
    file_id = _require_active_recording(file_id)
    ingest = provenance_for_file(file_id)
    if ingest is None:
        raise KnowledgeToolError("recording not found")
    try:
        lineage = transcript_provenance(file_id)
    except Exception:  # noqa: BLE001
        lineage = {}
    return {
        "file_id": file_id,
        "ingest": ingest,
        "transcript": lineage,
        "cloud_credentials_required": False,
    }


TOOL_HANDLERS = {
    "knowledge_search": knowledge_search,
    "knowledge_ask": knowledge_ask,
    "knowledge_list_recordings": knowledge_list_recordings,
    "knowledge_list_folders": knowledge_list_folders,
    "knowledge_list_tags": knowledge_list_tags,
    "knowledge_get_recording": knowledge_get_recording,
    "knowledge_get_transcript": knowledge_get_transcript,
    "knowledge_get_notes": knowledge_get_notes,
    "knowledge_get_provenance": knowledge_get_provenance,
}
