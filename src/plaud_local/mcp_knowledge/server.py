"""stdio (default) and optional HTTP stub for the local knowledge MCP.

Server name: ``localplaud-knowledge``. Distinct from:

* Official Plaud cloud ingest: ``@plaud-ai/mcp`` (see ``docs/plaud-api.md``)
* Hermes HTTP account adapter: ``scripts/localplaud_ro.py`` (``localplaud-readonly``)

Destructive / mutate tools are not registered in v1.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any

from .auth import KnowledgeMcpAuth, KnowledgeMcpAuthError, verify_http_bearer
from .tools import (
    READ_ONLY_TOOL_NAMES,
    KnowledgeToolError,
    knowledge_ask,
    knowledge_get_notes,
    knowledge_get_provenance,
    knowledge_get_recording,
    knowledge_get_transcript,
    knowledge_list_folders,
    knowledge_list_recordings,
    knowledge_list_tags,
    knowledge_search,
)

SERVER_NAME = "localplaud-knowledge"
SERVER_INSTRUCTIONS = (
    "Read-only knowledge tools over the localplaud / Plaud-local recording "
    "library (SQLite + artifacts). Never calls Plaud cloud or @plaud-ai/mcp and "
    "does not ingest recordings. Ask/semantic search use the app's configured "
    "embed/Ask profile and may leave the machine if cloud or remote-worker "
    "inference is opted in. knowledge_ask may write non-destructive "
    "provider_cost_reservations accounting rows (same as Web Ask)."
)


def _json_result(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def create_mcp(*, allow_mutations: bool = False):
    """Build the FastMCP server with read-only tools only.

    ``allow_mutations`` is accepted for forward compatibility but v1 never
    registers destructive tools even when True.
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised when extra missing
        raise SystemExit(
            "The 'mcp' package is required for the local knowledge MCP. "
            "Install with: uv sync --extra mcp   (or pip install 'mcp>=1,<2')"
        ) from exc

    mcp = FastMCP(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    @mcp.tool(
        name="knowledge_search",
        description=(
            "Search the local recording library (titles, transcripts, notes). "
            "Lexical by default; set semantic=true to use the app's configured "
            "embed profile (may leave the machine if cloud/remote embeddings are "
            "opted in). Never calls Plaud cloud or @plaud-ai/mcp; never requires "
            "Plaud OAuth credentials."
        ),
    )
    def tool_search(
        query: str,
        folder_id: int | None = None,
        tag_id: int | None = None,
        origin: str | None = None,
        limit: int = 20,
        semantic: bool = False,
    ) -> str:
        try:
            return _json_result(
                knowledge_search(
                    query,
                    folder_id=folder_id,
                    tag_id=tag_id,
                    origin=origin,
                    limit=limit,
                    semantic=semantic,
                )
            )
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    @mcp.tool(
        name="knowledge_ask",
        description=(
            "Ask a grounded question over the local library (or one recording when "
            "file_id is set). Uses the app's configured embed/Ask profile — may "
            "leave the machine if cloud or remote-worker inference is opted in. "
            "Never calls Plaud cloud or @plaud-ai/mcp. Does not mutate library "
            "content; may write non-destructive provider_cost_reservations "
            "accounting rows (same as Web Ask)."
        ),
    )
    def tool_ask(question: str, file_id: str | None = None, top_k: int = 6) -> str:
        try:
            return _json_result(knowledge_ask(question, file_id=file_id, top_k=top_k))
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — surface provider readiness to agents
            return _json_result({"error": f"Ask unavailable: {exc}"})

    @mcp.tool(
        name="knowledge_list_recordings",
        description="List bounded local recording metadata. Never downloads audio.",
    )
    def tool_list_recordings(
        query: str = "",
        origin: str | None = None,
        folder_id: int | None = None,
        tag_id: int | None = None,
        max_results: int = 20,
    ) -> str:
        try:
            return _json_result(
                knowledge_list_recordings(
                    query=query,
                    origin=origin,
                    folder_id=folder_id,
                    tag_id=tag_id,
                    max_results=max_results,
                )
            )
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    @mcp.tool(
        name="knowledge_list_folders",
        description="List folders in the local library with recording counts.",
    )
    def tool_list_folders() -> str:
        return _json_result(knowledge_list_folders())

    @mcp.tool(
        name="knowledge_list_tags",
        description="List tags in the local library with recording counts.",
    )
    def tool_list_tags() -> str:
        return _json_result(knowledge_list_tags())

    @mcp.tool(
        name="knowledge_get_recording",
        description="Get one recording's metadata, ingest provenance, and content flags.",
    )
    def tool_get_recording(file_id: str) -> str:
        try:
            return _json_result(knowledge_get_recording(file_id))
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    @mcp.tool(
        name="knowledge_get_transcript",
        description=(
            "Read the canonical local transcript as text with speakers/timestamps. "
            "Follow next_offset until end_of_document."
        ),
    )
    def tool_get_transcript(
        file_id: str,
        max_chars: int = 16_000,
        offset: int = 0,
        timestamps: bool = True,
        speakers: bool = True,
    ) -> str:
        try:
            return _json_result(
                knowledge_get_transcript(
                    file_id,
                    max_chars=max_chars,
                    offset=offset,
                    timestamps=timestamps,
                    speakers=speakers,
                )
            )
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    @mcp.tool(
        name="knowledge_get_notes",
        description=(
            "Read generated/edited notes as Markdown. Follow next_offset until "
            "end_of_document."
        ),
    )
    def tool_get_notes(file_id: str, max_chars: int = 16_000, offset: int = 0) -> str:
        try:
            return _json_result(
                knowledge_get_notes(file_id, max_chars=max_chars, offset=offset)
            )
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    @mcp.tool(
        name="knowledge_get_provenance",
        description=(
            "Return ingest transport provenance and canonical transcript lineage "
            "for one recording."
        ),
    )
    def tool_get_provenance(file_id: str) -> str:
        try:
            return _json_result(knowledge_get_provenance(file_id))
        except KnowledgeToolError as exc:
            return _json_result({"error": str(exc)})

    if allow_mutations:
        # v1: keep the flag but refuse to register mutate tools.
        sys.stderr.write(
            "localplaud-knowledge: allow_mutations requested but v1 ships "
            "read-only tools only; mutate tools remain absent.\n"
        )

    registered = {tool.name for tool in mcp._tool_manager.list_tools()}
    if registered != READ_ONLY_TOOL_NAMES:
        raise RuntimeError(
            f"localplaud-knowledge tool registry mismatch: got {sorted(registered)}, "
            f"expected {sorted(READ_ONLY_TOOL_NAMES)}"
        )
    return mcp


def build_http_auth_middleware(
    auth: KnowledgeMcpAuth | None = None,
) -> Callable[[str | None], None]:
    """Return a verifier callable for future HTTP transport wiring."""

    def _verify(authorization: str | None) -> None:
        verify_http_bearer(authorization, auth=auth)

    return _verify


def run_http_stub(*, host: str = "127.0.0.1", port: int = 8765) -> int:
    """Deferred HTTP transport: verify auth config and exit with guidance.

    Full streamable HTTP MCP is intentionally not shipped in v1. Operators who
    need remote access should put stdio behind an authenticated agent host or
    wait for a later phase. Auth helpers are exercised so fail-closed Bearer
    behaviour is already testable.
    """
    auth = KnowledgeMcpAuth.from_environ()
    try:
        # Probe fail-closed behaviour with a missing header.
        verify_http_bearer(None, auth=auth)
    except KnowledgeMcpAuthError as exc:
        sys.stderr.write(
            f"localplaud-knowledge HTTP stub: auth gate active ({exc}).\n"
            f"HTTP MCP transport is deferred; use stdio (default).\n"
            f"Configured listen would have been http://{host}:{port}/mcp\n"
            "Set LOCALPLAUD_KNOWLEDGE_MCP_TOKEN when HTTP mode ships.\n"
        )
        return 2
    sys.stderr.write(
        "localplaud-knowledge HTTP stub: token configured, but HTTP transport "
        f"is deferred in v1 (would bind {host}:{port}). Use --transport stdio.\n"
    )
    return 2


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="plaud-local-knowledge-mcp",
        description=(
            "Local knowledge MCP over the localplaud library "
            f"(server name: {SERVER_NAME}). Not @plaud-ai/mcp cloud ingest."
        ),
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio is the v1 default; http is a deferred stub",
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP stub bind host")
    parser.add_argument("--port", type=int, default=8765, help="HTTP stub bind port")
    parser.add_argument(
        "--allow-mutations",
        action="store_true",
        help="Ignored in v1: destructive tools remain absent",
    )
    args = parser.parse_args(argv)

    if args.transport == "http":
        raise SystemExit(run_http_stub(host=args.host, port=args.port))

    mcp = create_mcp(allow_mutations=args.allow_mutations)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
