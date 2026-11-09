"""Local knowledge MCP — read-only tools over the local recording library.

This package is the product MCP for search, Ask, transcripts, notes, and
provenance. It is **not** the official Plaud cloud ingest MCP
(``@plaud-ai/mcp`` / :class:`localplaud.plaud.mcp.PlaudMcpClient`) and is not
the Hermes HTTP account adapter (``scripts/localplaud_ro.py``).
"""

from .server import create_mcp, main
from .tools import READ_ONLY_TOOL_NAMES

__all__ = ["READ_ONLY_TOOL_NAMES", "create_mcp", "main"]
