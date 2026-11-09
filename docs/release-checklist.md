# Release / hardening checklist

Complete before tagging a Plaud-local milestone or claiming Phase 7 acceptance.

1. **Upstream pin** — [UPSTREAM.md](UPSTREAM.md) matches the intended localplaud
   ancestor; pin verify command succeeds; contribution/rebase notes current.
2. **Security** — [security-checklist.md](security-checklist.md) reviewed;
   [SECURITY.md](../SECURITY.md) advisory URL points at this product repo.
3. **Backup** — `pytest tests/test_backup_integrity.py tests/test_backups.py`
   green; optional operator isolated restore drill recorded.
4. **MCP** — knowledge MCP read-only tests green; docs still distinguish cloud
   ingest MCP vs local knowledge MCP.
5. **BLE claims** — release notes say **experimental / authorize deferred**; no
   GA BLE language (ADR 0011).
6. **Platform** — [platform-matrix.md](platform-matrix.md) matches shipping
   compose/docs; Docker BLE refusal unchanged.
7. **Performance** — [performance.md](performance.md) still accurate; no silent
   IGM concurrency increase.
8. **Attribution** — `NOTICE`, `ATTRIBUTION.md`, licence headers for any BLE
   vendor tree present.
9. **CI** — GitHub Actions green on the release revision.
10. **Open questions** — closed vs deferred registry updated in the project
    store / docs as applicable.
