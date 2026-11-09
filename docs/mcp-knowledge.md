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

Tools read the **local** library SoR. No Plaud OAuth. Read-only library
mutations in v1. Ask/semantic search still honor the app's configured inference
profile (see Safety).

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
# or: python -m plaud_local.mcp_knowledge
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
| `knowledge_search` | Lexical library search; optional `semantic=true` via configured embed profile |
| `knowledge_ask` | Grounded Ask (library or `file_id` scope) via configured Ask profile |
| `knowledge_list_recordings` | Bounded recording metadata |
| `knowledge_list_folders` | Folders + counts |
| `knowledge_list_tags` | Tags + counts |
| `knowledge_get_recording` | Metadata + ingest provenance flags |
| `knowledge_get_transcript` | Canonical transcript text (paginated) |
| `knowledge_get_notes` | Notes Markdown (paginated) |
| `knowledge_get_provenance` | Ingest transport + transcript lineage |

Destructive tools (delete, edit, reprocess, cloud write, device admin) are
**absent** in v1. `--allow-mutations` is ignored and prints a warning.

`knowledge_ask` does not mutate library content, but may write non-destructive
`provider_cost_reservations` accounting rows (same path as Web Ask).

---

## Safety

- Default transport: **stdio** (OS user boundary; no network listener).
- HTTP + Bearer is **deferred**; `plaud-local-knowledge-mcp --transport http` runs
  an auth-aware stub and exits. When HTTP ships, set
  `LOCALPLAUD_KNOWLEDGE_MCP_TOKEN` and keep auth fail-closed.
  `LOCALPLAUD_KNOWLEDGE_MCP_REQUIRE_AUTH=0` exists for local debugging only and
  must be treated as **explicitly dangerous** if HTTP transport is ever bound to
  a network interface.
- Library data plane is local. Ask / optional semantic search use the app's
  configured embed/Ask profile and **may leave the machine** if cloud or
  remote-worker inference is opted in. They never call Plaud cloud or
  `@plaud-ai/mcp`, and responses set `cloud_credentials_required: false` for
  Plaud OAuth (not a claim that inference is air-gapped).
- No raw credential export; no Plaud cloud writes via this server.
- get/list payloads omit `audio_path` and other raw filesystem paths.

---

## Related docs

- Official cloud MCP client: [plaud-api.md](plaud-api.md)
- Hermes account reader seed: [hermes-account-reader.md](hermes-account-reader.md)
- Ingest provenance fields: [ingest-dedupe.md](ingest-dedupe.md)
