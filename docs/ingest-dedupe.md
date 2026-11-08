# Ingest & duplicate detection (Phase 3)

Plaud-local adds a **unified ingestion orchestrator** on top of localplaud’s
existing cloud poller and local upload paths. Library-level duplicate detection
is conservative: **link by default, never silent-delete or overwrite originals**.

## Backends

| Backend | Transport | Status |
| --- | --- | --- |
| Cloud poller | `cloud` | Reuses official Open API / MCP listing + download |
| Filesystem | `filesystem` | Import an on-disk audio path |
| Upload | `upload` | Multipart / Web App “Add audio” |
| BLE | `ble` | **Experimental** — OpenPlod-adapted adapter (`docs/ble.md`); `serial:sessionId`; radio needs bridge + identity |

Feature flag: `[ingest] enabled` in `config.toml` (default `true`). When
`enabled = false`, fall back to poller + legacy upload-only behaviour.

## Dedupe policy

Configured by `ingest.dedupe_mode`:

| Mode | Behaviour |
| --- | --- |
| `off` | No library graph matching (identity PK upsert for cloud ids still applies) |
| `link` (**default**) | Same external id → reuse row; same content hash / fingerprint → create linked row with `duplicate_of` |
| `reject_new` | Refuse creating a second library row; return the existing id |

**Never** deletes, merges, or overwrites an original recording’s audio or
artifacts as part of dedupe.

Match priority:

1. External id (`provider` + `transport` + `external_id`), including BLE
   `serial:sessionId`
2. `content_sha256` of audio bytes
3. Optional `audio_fingerprint` (column + hook only; no algorithm in Phase 3)

## Provenance

- `plaud_files.source_transport` — `cloud` \| `upload` \| `filesystem` \| `ble`
- `plaud_files.content_sha256`, optional `audio_fingerprint`
- `plaud_files.duplicate_of` / `dedupe_status`
- `recording_external_ids` — durable identity graph per workspace

Legacy `origin` (`plaud` / `local`) is preserved. Independent-mode transcript /
summary artifacts are **not** rewritten by this migration.

Query: `GET /api/ingest/files/{file_id}/provenance`

## API surface

- `GET /api/ingest/status` — flags + backend inventory
- `POST /api/ingest/cloud/poll` — official catalog check
- `POST /api/ingest/filesystem` — path ingest
- `POST /api/ingest/upload` — orchestrated upload
- `POST /api/ingest/ble/stub` — BLE-shaped candidate (no radio transfer)
- Existing `POST /api/imports/local/audio` routes through the orchestrator when
  ingest is enabled (adds `outcome` / `duplicate_of` fields)

## Resume / retry

`ingest_jobs` journals orchestrated imports. On process restart, running jobs
are marked failed; a retry with the same external key or content hash **reuses**
the completed file id instead of creating a second row.

## Migration

`migrate_ingest_dedupe_schema` is additive and idempotent (localplaud style).
It backfills `source_transport` from `origin` and seeds Plaud cloud external
ids. Rollback: restore a DB backup and set `ingest.enabled = false`.
