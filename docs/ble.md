# Bluetooth Note Pro adapter (experimental / deferred)

Phase 4 adds an **isolated** BLE adapter adapted from
[OpenPlod](https://github.com/RemiPelloux/OpenPlod) (MIT) so Plaud-local can
eventually authorize a Note Pro and ingest decoded audio into the Phase 3
orchestrator. Vault, UI, and transcription stay **localplaud** — the full
OpenPlod app is **not** installed or merged.

**Status (2026-11):** **experimental / not GA**; live authorize/download is
**deferred**. Feature flag `[ble] enabled = false` by default. Protocol **20** /
Note Pro (advertisement projects 881/883) only. No Android. Policy:
[ADR 0011](adr/0011-ble-experimental-policy.md).

### What you can rely on

| Path | Status |
| --- | --- |
| Cloud Open API (`localplaud auth login` + poll/download) | **Supported** |
| Filesystem / Web upload ingest | **Supported** |
| Mac BLE scan / bridge detection | **Proven** in live trials (experimental) |
| BLE authorize → `plaud-device.json` (Partner `gen-key` / `sn-sign`) | **Deferred** — Partner SDK returns HTTP 500 for official OAuth tokens; consumer JWTs rejected |
| Linux full BLE download | **Not verified** |
| Windows WinRT scan | **Not verified** (bridge may build; detection failed in trials) |
| BLE inside default Docker images | **Unsupported** (doctor fails if enabled) |

### Supported recording path right now

Use the **official Plaud Open API** (cloud poll/download):

```bash
uv run localplaud auth login   # one-time browser OAuth
uv run localplaud poll --once  # or `localplaud run` / scheduled poll
```

Do **not** treat BLE Note Pro radio ingest as a supported product path until
Partner SDK device authorization works for the account (see below). Do **not**
describe BLE as production-ready, GA, or “authorized device sync.” Compile
evidence for `plaud-bridge` is **not** transfer acceptance.

Host packaging (BlueZ / Docker refusal / Windows policy): [ble-host.md](ble-host.md).

## Why BLE authorize is deferred

Live Mac testing showed:

| Token source | Partner `POST …/partner/sdk/gen-key` |
| --- | --- |
| Consumer web session (`pld_ut` / Chrome extract, EU `api-euc1`) | **ACCESS_TOKEN_INVALID** on `platform-us` and `platform-jp` |
| Official Open API OAuth (`localplaud auth login`) | **HTTP 500** on `platform-us` and `platform-jp` |

There is **no** published EU Partner host (`platform-euc1` / `platform-eu` do
not resolve). `developer-euc1.plaud.ai` exists but the Partner `gen-key` path
is **404**. Without a successful `gen-key` + `sn-sign`, no `plaud-device.json`
is written, so BLE list/import cannot run.

Mac **scan / CoreBluetooth bridge / connection verify** worked when the owner
held the device button. Windows WinRT **scan** did not find advertisements in
earlier probes. Neither path completed authorize.

The BLE **code remains in-tree** for a later resume when Plaud Partner SDK
accepts a mintable token (or an alternate authorize path is documented).

## What lands in-tree (kept)

1. **Provision CLI/module** (`localplaud ble provision`) — paste/file token →
   Partner SDK `gen-key` + `sn-sign` → private `plaud-device.json` (0600).
2. **Isolated package** `src/localplaud/ble/` → Phase 3 ingest
   (`source_transport=ble`, `serial:sessionId`) when identity + transfer exist.
3. **Vendored** `plaud-bridge` under `vendor/openplod-ble/` (MIT + NOTICE).
4. Helpers: `scripts/extract_plaud_chrome_token.py` (macOS Chrome cookies → EU
   refresh; does **not** bypass Partner rejection).
5. Tests: mocked provision + protocol fixtures + BLE ingest dedupe (no live secrets).

## Resume later (operator checklist)

1. Confirm Partner `gen-key` succeeds for a real token (us/jp or a future EU host).
2. `localplaud ble provision --serial … --identifier … --token-file …`
   (macOS identifier is a CoreBluetooth **UUID**, not a MAC).
3. Build bridge: `cd vendor/openplod-ble/plaud-bridge && cargo build --release`
   (or packaging script / `LOCALPLAUD_BLE__BRIDGE_PATH`).
4. Optionally `[ble] enabled = true`; keep device awake / button-held for ads.
5. `localplaud ble doctor` then scan / transfer / Phase 3 ingest.
6. Release notes may then narrow “deferred authorize”; GA still needs a written
   acceptance matrix.

Partner portal `client_id` / `client_secret` is **not** required by the
paste-token code path. Whether Plaud accepts a given JWT remains **server-side**.

## Identity file

Writes private `plaud-device.json` (mode `0600` on POSIX):

| Platform | Default path |
| --- | --- |
| All (source run) | `./data/plaud-device.json` |
| Override | `LOCALPLAUD_BLE__IDENTITY_PATH` or `--identity-path` |

**Never commit** this file. It holds binding token, signature, and RSA keys.

Regions currently coded: `platform-us.plaud.ai` (default), `platform-jp.plaud.ai`.

## Build the radio bridge

```bash
cd vendor/openplod-ble/plaud-bridge
cargo build --release
```

Set `LOCALPLAUD_BLE__BRIDGE_PATH` or place the binary on `PATH` / `./bin/`.
Source notice: `vendor/openplod-ble/NOTICE`.

## Doctor / CLI

| Command | Purpose |
| --- | --- |
| `localplaud ble doctor` | Redacted readiness (flag, bridge, identity, ffmpeg) |
| `localplaud ble provision` | Token → Partner SDK → `plaud-device.json` (deferred live) |
| `localplaud ble scan` | Optional scan when bridge present (redacted) |
| `localplaud ble scan-verbose` | Count ads vs filter rejects (no MAC/serial) |
| `localplaud ble clear-identity --yes` | Delete local authorization |

### macOS CoreBluetooth identifier

On macOS, CoreBluetooth does **not** expose a Bluetooth MAC. `plaud-bridge`
therefore reports the CoreBluetooth peripheral UUID as `identifier` (not
`00:00:00:00:00:00`). Use that UUID with `ble provision --identifier`.

### WinRT scan filter (vs Mac)

Mac name matching vs WinRT manufacturer/service gaps: see bridge comments and
`scan-verbose` count-only diagnostics. Windows live scan was **not** verified
to detect the owner's Note Pro in Phase 4 probes.

Optional Python crypto: `pip install 'localplaud[ble]'` (ChaCha20 / RSA unwrap).

## Attribution

See root `NOTICE`, `ATTRIBUTION.md`, and `vendor/openplod-ble/NOTICE`.
OpenPlod MIT Copyright 2026 Remi Pelloux and contributors; openplaud inheritance
residual risk accepted by the owner for this selective adapter.
