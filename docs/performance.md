# Performance notes (personal-scale library)

Plaud-local targets a **personal** library: hundreds to low thousands of
recordings, thousands of embedding chunks — not multi-tenant SaaS scale.

## What is in scope today

| Area | Behaviour | Guidance |
| --- | --- | --- |
| Embeddings / Ask retrieval | Brute-force cosine over SQLite `chunks` float32 blobs (ADR 0005) | Fine at personal scale (typically single-digit ms for thousands × ~384-d) |
| IGM / local LLM | **Concurrency 1**; HTTP 409 busy → retry/backoff | Serialize Ask + pipeline; surface queue/busy UX — do not fake parallelism |
| Pipeline stages | Durable, independently resumable | Prefer resume over full recompute after stage failures |
| Backups | Online SQLite snapshot; full media optional | Full archives need FD headroom and disk for snapshot + ZIP |
| Docker core | CPU orchestration; heavy ASR/LLM on host or remote worker | AMD Strix Halo → IGM/ROCm on host, not Compose `gpu` (CUDA) |

## When personal-scale stops fitting

If Ask latency or memory grows unacceptable (large chunk counts, multi-user, or
very high-dimensional embeddings):

1. Measure: chunk count, embedding dim, Ask p95, RSS during retrieve.
2. Consider an external vector index (Chroma, Qdrant, or equivalent) behind the
   existing retrieve API — **deferred** until personal-scale fails
   (open question Q-ARC-5).
3. Keep audio on the filesystem and canonical transcripts in SQLite; only move
   vector search.

## Load sanity (Phase 7)

- Concurrent Ask + pipeline against IGM must tolerate 409 without dropping work.
- Do not raise gateway concurrency above 1 on the shared Strix Halo gateway
  without an explicit operator decision.
- CI does not run multi-GB libraries; treat large-library behaviour as an
  operator drill, not a green CI claim.
