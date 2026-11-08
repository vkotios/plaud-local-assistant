"""Content hashing helpers for library-level duplicate detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 << 20


def content_sha256_of_path(path: Path | str) -> str:
    """SHA-256 hex digest of file bytes (streaming)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256_of_bytes(data: bytes) -> str:
    """SHA-256 hex digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()


def optional_fingerprint_stub(
    *,
    content_sha256: str | None = None,
    enabled: bool = False,
) -> str | None:
    """Optional audio fingerprint hook.

    Phase 3 ships the column and call site only. No acoustic fingerprint
    algorithm is bundled; when enabled without a real implementation, return
    None so callers never invent a false-positive merge key.
    """
    del content_sha256  # reserved for future acoustic fingerprint backends
    if not enabled:
        return None
    return None
