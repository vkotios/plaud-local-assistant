# Upstream pin

Plaud-local is initialized from **localplaud** with full git history preserved.

| Field | Value |
| --- | --- |
| Upstream repository | https://github.com/skyhong2002/localplaud |
| Upstream remote name | `upstream` (local clones) |
| Pinned commit | `5d7d1c9202b4e7340966ed63fc72d99624528d84` |
| Pinned date | 2026-11-04 |
| Pinned subject | Publish a landing page and read-only live demo on GitHub Pages |
| Licence | MIT |

## Tracking posture

- Prefer wrap/adapt overlays over rewriting `worker/pipeline.py` or `api/app.py`.
- Record rebase/merge upgrades here when the pin moves.
- Do not vendor OpenPlod in the same change as an upstream pin bump unless Phase 4
  licence gates are already cleared.

## Verify the pin

```bash
git merge-base --is-ancestor 5d7d1c9202b4e7340966ed63fc72d99624528d84 HEAD \
  && echo "pinned localplaud commit is an ancestor of HEAD"
```
