# ADR 0009: Fork / wrap boundary for localplaud

Status: Accepted

## Context

Plaud-local needs localplaud's recording library, pipeline, and Web App, plus
product overlays (IGM client defaults, ingest dedupe, knowledge MCP, packaging,
experimental BLE). A full early fork maximises control but creates rebase pain;
a pure external package dependency would block schema and UI changes.

## Decision

- **Wrap-first / overlay-in-tree:** this repository **is** a git history fork of
  localplaud with Plaud-local overlays living beside upstream modules
  (`src/plaud_local/`, docs overlays, packaging scripts).
- Prefer additive packages and docs over rewriting `worker/pipeline.py` or
  `api/app.py`.
- Pin upstream via [UPSTREAM.md](../UPSTREAM.md); record every pin bump and
  rebase there.
- Do not vendor OpenPlod / BLE protocol in the same change as an upstream pin
  bump unless BLE licence gates are already cleared.
- Treat a deeper fork (permanent divergence without rebase cadence) as a later
  decision only if overlay isolation fails.

## Consequences

- Operators and contributors follow the upstream contribution rules plus
  Plaud-local overlay notes in [UPSTREAM.md](../UPSTREAM.md).
- Rebase discipline is mandatory; CI must stay green after pin moves.
- Product branding and IGM/Fedora defaults can diverge without blocking
  localplaud security fixes from merging.
