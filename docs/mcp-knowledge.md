# Local knowledge MCP vs Plaud cloud ingest MCP

Plaud-local exposes **two different MCP planes**. Mixing them up sends agents to
the wrong data plane or the wrong credentials.

| MCP | Package / entrypoint | Authority | Role |
| --- | --- | --- | --- |
| **Plaud cloud ingest** | Official `@plaud-ai/mcp` via `localplaud.plaud.mcp.PlaudMcpClient` | Plaud OAuth (`~/.plaud/tokens-mcp.json`) | Read-only cloud listing + raw-audio download for sync |
| **Local knowledge** | `plaud-local-knowledge-mcp` → `plaud_local.mcp_knowledge` | Local library (OS user / optional Bearer later) | Search, Ask, transcripts, notes, provenance over **local** SoR |

The Hermes adapter `scripts/localplaud_ro.py` (`localplaud-readonly`) remains a
narrow HTTP account seed for diagnostics — it is **not** this product MCP.

---

## Diagram 1 — Plaud cloud ingest MCP (official)

Cloud credentials only. Used as an alternate ingest transport; never as the
product knowledge surface.

```text
┌────────────────────┐     stdio / official tools      ┌──────────────────────────┐
│  Agent / localplaud│ ──────────────────────────────► │  @plaud-ai/mcp            │
│  PlaudMcpClient    │   get_current_user, list_files, │  (Plaud cloud)            │
│                    │   get_file, get_note*,          │                           │
│                    │   get_transcript*               └────────────┬─────────────┘
└────────────────────┘                                              │
                                                                    ▼
                                                         Plaud Open API / cloud
                                                         (raw audio + metadata)
                                                                    │
                                                                    ▼
                                                         localplaud poller/ingest
                                                         → local library SoR
```

\* `get_note` / `get_transcript` are migration/debug inputs only and must not
satisfy subscription-independence acceptance. See [plaud-api.md](plaud-api.md).

---

## Diagram 2 — Local knowledge MCP (product)

Local library only. No Plaud cloud credentials. Read-only in v1.

```text
┌────────────────────┐     stdio (default)             ┌──────────────────────────┐
│  Desktop agent     │ ──────────────────────────────► │  localplaud-knowledge    │
│  (Cursor, etc.)    │   knowledge_search              │  plaud_local.mcp_knowledge│
│                    │   knowledge_ask                 │                           │
│                    │   knowledge_list_*              │  optional HTTP + Bearer   │
│                    │   knowledge_get_*               │  (stubbed / deferred)     │
└────────────────────┘                                 └────────────┬─────────────┘
                                                                    │
                                                                    ▼
                                                         local SQLite + artifacts
                                                         (search / Ask / export)
                                                                    ▲
                                                                    │
                                                         Web UI / HTTP API
                                                         (same library)
```

---

## Install and run (stdio)

```bash
uv sync --extra mcp
# Point at your local library DB (same as the app):
#   LOCALPLAUD_STORE__DATABASE_URL=sqlite:////path/to/localplaud.db
uv run plaud-local-knowledge-mcp
# or: python -m plaud_local.mcp_knowledge.server
```

Example Cursor / MCP client config sketch:

```json
{
  "mcpServers": {
    "localplaud-knowledge": {
      "command": "uv",
      "args": ["run", "plaud-local-knowledge-mcp"],
      "env": {
        "LOCALPLAUD_STORE__DATABASE_URL": "sqlite:////var/lib/localplaud/localplaud.db"
      }
    }
  }
}
```

Do **not** point this config at `@plaud-ai/mcp`, and do not put Plaud OAuth tokens
in the knowledge MCP environment.

---

## Tools (v1, read-only)

| Tool | Purpose |
| --- | --- |
| `knowledge_search` | Lexical library search; optional `semantic=true` |
| `knowledge_ask` | Grounded Ask (library or `file_id` scope) |
| `knowledge_list_recordings` | Bounded recording metadata |
| `knowledge_list_folders` | Folders + counts |
| `knowledge_list_tags` | Tags + counts |
| `knowledge_get_recording` | Metadata + ingest provenance flags |
| `knowledge_get_transcript` | Canonical transcript text (paginated) |
| `knowledge_get_notes` | Notes Markdown (paginated) |
| `knowledge_get_provenance` | Ingest transport + transcript lineage |

Destructive tools (delete, edit, reprocess, cloud write, device admin) are
**absent** in v1. `--allow-mutations` is ignored and prints a warning.

---

## Safety

- Default transport: **stdio** (OS user boundary; no network listener).
- HTTP + Bearer is **deferred**; `plaud-local-knowledge-mcp --transport http` runs
  an auth-aware stub and exits. When HTTP ships, set
  `LOCALPLAUD_KNOWLEDGE_MCP_TOKEN` and keep auth fail-closed.
- Responses advertise `cloud_credentials_required: false`.
- No raw credential export; no Plaud cloud writes via this server.

---

## Related docs

- Official cloud MCP client: [plaud-api.md](plaud-api.md)
- Hermes account reader seed: [hermes-account-reader.md](hermes-account-reader.md)
- Ingest provenance fields: [ingest-dedupe.md](ingest-dedupe.md)
