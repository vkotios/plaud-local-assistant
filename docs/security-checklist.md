# Plaud-local security checklist (release / Phase 7)

Use this before claiming a hardening or release milestone. Evidence classes:
**Verified** (test/CI), **Documented**, **Deferred**.

## Secrets layout

| Check | Expected | Evidence |
| --- | --- | --- |
| Secrets outside Git | `.env`, `config.toml`, tokens, `secrets/`, `data/` gitignored | Documented (`.gitignore`, `.env.example`) |
| No secrets in backups | Archives omit `.env`, OAuth tokens, provider secret values | Verified (`tests/test_backups.py`, `docs/backups.md`) |
| IGM inference key ≠ control-plane key | Documented; env-only | Documented (`docs/deploy-fedora-igm.md`) |
| BLE identity files | `plaud-device.json` never committed; experimental path only | Documented (`NOTICE`, BLE ADRs) |

## MCP auth

| Check | Expected | Evidence |
| --- | --- | --- |
| Knowledge MCP ≠ `@plaud-ai/mcp` | Distinct names/entrypoints/docs | Documented (`docs/mcp-knowledge.md`, ADR 0010) |
| Default knowledge MCP | Read-only stdio; no mutate tools | Verified (`tests/test_mcp_knowledge.py`) |
| HTTP Bearer | Fail-closed when auth required and token unset | Verified (`tests/test_mcp_knowledge.py`) |
| HTTP transport | Deferred / stubbed for v1 remote agents | Documented |

## SSRF and fetches

| Check | Expected | Evidence |
| --- | --- | --- |
| Signed URL fetches | HTTPS only; deny private/loopback/link-local/reserved | Documented (ADR 0006); helpers in `plaud/common.py` |
| Redirects | Not followed after the check | Documented |
| Download bounds | Audio ≤ 2 GiB; gzip decompress bounded | Documented (ADR 0006) |
| Backup upload destinations | Explicit allow; private/LAN only when opted in; no redirects | Documented (`docs/backups.md`) |

## Web / accounts

| Check | Expected | Evidence |
| --- | --- | --- |
| Default bind | Loopback | Documented |
| Network exposure | Accounts + session secret + HTTPS | Documented (`SECURITY.md`, `docs/accounts.md`) |
| Auth gates | Token / session / account tests | Verified (`tests/test_security.py`) |

## Backup / restore

| Check | Expected | Evidence |
| --- | --- | --- |
| Isolated restore | Trusted digest required; new destination only | Verified (`tests/test_backup_integrity.py`) |
| Seal after hash | Extract from private sealed copy | Verified (Phase 7 fix) |
| Corrupt/unsafe members | Rejected; destination cleaned | Verified |

## Policy

| Check | Expected | Evidence |
| --- | --- | --- |
| Private/RE Plaud APIs | Permanently rejected | Documented (`NOTICE`, preferences) |
| BLE GA claims | Forbidden until hardware acceptance | Documented (ADR 0011; experimental only) |
| Vulnerability reports | Private advisory channel | Documented (`SECURITY.md`) |

## Operator pre-flight

1. Confirm `.env` / tokens are not world-readable and not in Git.
2. Run `localplaud doctor`.
3. Create a **database-only** then a **full** backup; run an isolated restore drill
   into a fresh directory with the trusted SHA-256.
4. If exposing beyond loopback: enable accounts, set session secret, terminate TLS.
5. Keep knowledge MCP on stdio unless HTTP auth is deliberately configured.
