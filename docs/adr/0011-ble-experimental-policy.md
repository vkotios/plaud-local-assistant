# ADR 0011: BLE Note Pro experimental / deferred policy

Status: Accepted

## Context

Note Pro BLE transfer (OpenPlod-adapted, protocol 20) is valuable for
offline/device ingest, but live **authorize** (Partner `gen-key` / `sn-sign` →
`plaud-device.json`) is blocked on Plaud's Partner SDK for the project account
(HTTP 500 on official OAuth tokens; consumer JWTs rejected). Mac scan/bridge is
proven; Linux full download remains Not verified; Windows WinRT scan was not
detected in trials. Cloud Open API ingest works independently.

## Decision

- BLE is **experimental**, feature-flagged off by default, and **not GA**.
- **Do not** claim production BLE download or “authorized device sync” in
  release notes until Partner authorize succeeds and at least one end-to-end
  import is evidenced on a declared OS.
- **Supported ingest** for operators today: official Plaud Open API
  (`localplaud auth login` + poll/download) and filesystem/upload paths.
- Keep adapter code isolatable (vendor tree / `ble` package) with MIT
  attribution; openplaud provenance residual risk is owner-accepted.
- Default Docker/compose profiles **refuse** BLE; host BlueZ path only
  ([ble-host.md](../ble-host.md)).
- Phase 4 live authorize/download is **deferred** (server-side Partner failure),
  not a radio/pairing defect. See store closeout
  `docs/phase4-ble-deferred.md` when present.

## Consequences

- Packaging and CI may compile `plaud-bridge` as compile evidence only.
- README / CHANGELOG must say experimental / deferred authorize explicitly.
- Resuming BLE requires a successful `gen-key` + provision + one library import;
  until then cloud Open API remains the supported path.
