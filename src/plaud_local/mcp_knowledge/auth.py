"""Auth helpers for the local knowledge MCP.

stdio transport relies on the OS user boundary (no network credentials).
Optional HTTP mode (deferred for v1 remote agents) uses a Bearer API key with
constant-time comparison. Patterns seeded from the Hermes account adapter's
least-privilege posture and PlaudNotes-style Bearer middleware — without
password-file login or cloud credentials.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass


class KnowledgeMcpAuthError(PermissionError):
    """Raised when an HTTP Bearer token is missing or invalid."""


@dataclass(frozen=True, slots=True)
class KnowledgeMcpAuth:
    """Bearer key configuration for optional HTTP transport."""

    bearer_token: str | None = None
    require_auth: bool = True

    @classmethod
    def from_environ(cls, environ: dict[str, str] | None = None) -> KnowledgeMcpAuth:
        env = environ if environ is not None else os.environ
        token = (env.get("LOCALPLAUD_KNOWLEDGE_MCP_TOKEN") or "").strip() or None
        require_raw = (env.get("LOCALPLAUD_KNOWLEDGE_MCP_REQUIRE_AUTH") or "1").strip().lower()
        require_auth = require_raw not in {"0", "false", "no", "off"}
        return cls(bearer_token=token, require_auth=require_auth)


def constant_time_equals(left: str, right: str) -> bool:
    """Compare secrets without leaking length via early exit on mismatch."""
    left_digest = hashlib.sha256(left.encode("utf-8")).digest()
    right_digest = hashlib.sha256(right.encode("utf-8")).digest()
    return hmac.compare_digest(left_digest, right_digest)


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, remainder = authorization.strip().partition(" ")
    if scheme.lower() != "bearer" or not remainder.strip():
        return None
    return remainder.strip()


def verify_http_bearer(
    authorization: str | None,
    auth: KnowledgeMcpAuth | None = None,
) -> None:
    """Reject unauthenticated or mismatched Bearer tokens for HTTP mode.

    When ``require_auth`` is true (default) and no server token is configured,
    every request is rejected — fail closed rather than expose the library.
    """
    auth = auth or KnowledgeMcpAuth.from_environ()
    if not auth.require_auth:
        return
    expected = auth.bearer_token
    if not expected:
        raise KnowledgeMcpAuthError(
            "LOCALPLAUD_KNOWLEDGE_MCP_TOKEN is not configured; HTTP mode refuses "
            "unauthenticated access"
        )
    provided = extract_bearer_token(authorization)
    if provided is None:
        raise KnowledgeMcpAuthError("missing or invalid Authorization Bearer header")
    if not constant_time_equals(provided, expected):
        raise KnowledgeMcpAuthError("invalid Bearer token")
