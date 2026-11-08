"""Unified multi-source ingestion and library-level duplicate detection.

Phase 3 surface for Plaud-local. Backends wrap existing cloud poller / upload
paths and a BLE stub; dedupe is conservative (link by default, never silent
delete or overwrite of originals).
"""

from __future__ import annotations

from .backends import BleBackend, CloudBackend, FilesystemBackend, UploadBackend
from .dedupe import DedupeDecision, resolve_duplicates
from .hashing import content_sha256_of_bytes, content_sha256_of_path
from .orchestrator import (
    IngestCandidate,
    IngestResult,
    IngestStatus,
    ingest_candidate,
    ingest_status,
    recover_interrupted_ingest_jobs,
)

__all__ = [
    "BleBackend",
    "CloudBackend",
    "DedupeDecision",
    "FilesystemBackend",
    "IngestCandidate",
    "IngestResult",
    "IngestStatus",
    "UploadBackend",
    "content_sha256_of_bytes",
    "content_sha256_of_path",
    "ingest_candidate",
    "ingest_status",
    "recover_interrupted_ingest_jobs",
    "resolve_duplicates",
]
