# Upstream pin and rebase discipline

Plaud-local is initialized from **localplaud** with full git history preserved.
See [ADR 0009](adr/0009-fork-wrap-boundary.md) for the fork/wrap boundary.

| Field | Value |
| --- | --- |
| Upstream repository | https://github.com/skyhong2002/localplaud |
| Upstream remote name | `upstream` (local clones) |
| Product repository | https://github.com/vkotios/plaud-local-assistant |
| Pinned commit | `5d7d1c9202b4e7340966ed63fc72d99624528d84` |
| Pinned date | 2026-11-04 |
| Pinned subject | Publish a landing page and read-only live demo on GitHub Pages |
| Licence | MIT |

## Tracking posture

- Prefer wrap/adapt overlays over rewriting `worker/pipeline.py` or `api/app.py`.
- Record rebase/merge upgrades in the table below when the pin moves.
- Do not vendor OpenPlod in the same change as an upstream pin bump unless Phase 4
  licence gates are already cleared.
- Keep Plaud-local packages under `src/plaud_local/` and docs overlays easy to
  re-apply after a rebase.

## Verify the pin

```bash
git remote add upstream https://github.com/skyhong2002/localplaud.git 2>/dev/null || true
git fetch upstream main
git merge-base --is-ancestor 5d7d1c9202b4e7340966ed63fc72d99624528d84 HEAD \
  && echo "pinned localplaud commit is an ancestor of HEAD"
```

## Contribution / rebase notes

1. **Add the upstream remote** (once per clone) and fetch before bumping the pin.
2. **Rebase or merge** `upstream/main` onto a dedicated branch
   (`cursor/upstream-bump-…`). Resolve conflicts in overlay files deliberately;
   prefer upstream for shared localplaud modules unless a Plaud-local fix must
   stay.
3. **Update this document** (pin commit, date, subject) in the same PR as the
   bump.
4. **Run CI locally** at least: `ruff check`, focused pytest for touched areas,
   and `tests/test_backup_integrity.py` after backup-related upstream changes.
5. **Do not** combine an upstream bump with BLE vendor drops, private API
   experiments, or unrelated refactors.
6. **Attribute** MIT upstream; keep `NOTICE` / `ATTRIBUTION.md` accurate when
   BLE or other third-party trees change.
7. **Contribute fixes upstream** when they are generic localplaud improvements;
   keep Plaud-local-only behaviour (IGM defaults, Fedora packaging, knowledge
   MCP product naming) in overlays.

### Suggested bump checklist

```bash
git fetch upstream main
git checkout -b cursor/upstream-bump-<shortsha>-700b
git merge upstream/main   # or: git rebase upstream/main
# fix conflicts; update docs/UPSTREAM.md pin table
uv run ruff check src tests
uv run pytest tests/test_backup_integrity.py tests/test_security.py tests/test_mcp_knowledge.py -q
```

## Pin history

| Date | Pin | Notes |
| --- | --- | --- |
| 2026-11-04 | `5d7d1c9202b4e7340966ed63fc72d99624528d84` | Initial Plaud-local pin (landing page / live demo commit) |
