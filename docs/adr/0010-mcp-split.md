# ADR 0010: Cloud ingest MCP vs local knowledge MCP

Status: Accepted

## Context

Plaud publishes an official cloud MCP (`@plaud-ai/mcp`) for account/library
ingest. Operators also want agents to query the **local** library (transcripts,
notes, Ask) without sending that corpus through Plaud. Mixing the two planes
causes credential and data-boundary mistakes.

## Decision

- **Two MCP planes, never one:**
  - **Cloud ingest MCP** — official `@plaud-ai/mcp`; Plaud OAuth; read Plaud
    cloud. Not a substitute for local Ask.
  - **Local knowledge MCP** — product entrypoint `plaud-local-knowledge-mcp` /
    `python -m plaud_local.mcp_knowledge`; server name `localplaud-knowledge`;
    reads the local SQLite library only.
- Knowledge MCP is **read-only by default** (no delete/edit tools). Optional
  `--allow-mutations` must not register destructive tools in v1.
- Default transport is **stdio** (OS user boundary). HTTP + Bearer is
  fail-closed and **deferred** for v1 remote exposure.
- Knowledge MCP may use the app's configured embed/Ask profile (including
  opt-in cloud/IGM inference). It must **never** call Plaud cloud or private
  Plaud APIs.

## Consequences

- Docs and CLI names must stay distinct ([mcp-knowledge.md](../mcp-knowledge.md)).
- Security review treats HTTP knowledge MCP as a library-exfiltration risk until
  auth and bind address are deliberately configured.
- Hermes / account-reader seeds are diagnostics only — not this product MCP.
