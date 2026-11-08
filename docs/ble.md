# Bluetooth Note Pro adapter (experimental)

Phase 4 adds an **isolated** BLE adapter adapted from
[OpenPlod](https://github.com/RemiPelloux/OpenPlod) (MIT) so Plaud-local can
authorize a Note Pro and ingest decoded audio into the Phase 3 orchestrator.
Vault, UI, and transcription stay **localplaud** — the full OpenPlod app is
**not** installed or merged.

**Status:** experimental. Feature flag `[ble] enabled = false` by default.
Protocol **20** / Note Pro (advertisement projects 881/883) only. No Android.

## What you must do once (owner)

1. Sign in at [web.plaud.ai](https://web.plaud.ai).
2. Open browser DevTools → **Application** → **Local Storage** →
   `https://web.plaud.ai` → copy **`tokenstr`**.
3. Wake the Note Pro near the PC. Note its Bluetooth address (or run a scan
   once `plaud-bridge` is built).
4. Provision (token via prompt / `--token-file` / stdin — prefer file over shell
   history):

   ```bash
   localplaud ble provision \
     --serial <16-HEX-SERIAL> \
     --identifier <BD_ADDR-or-UUID>
   ```

5. Confirm readiness (output is redacted):

   ```bash
   localplaud ble doctor
   ```

Partner portal `client_id` / `client_secret` is **not** required for this path.
Whether Plaud accepts a fresh consumer JWT on Partner SDK `gen-key` / `sn-sign`
is **server-side / unverified** for some accounts (OpenPlod documented the same
caveat). If Plaud returns `CLIENT_USER_NOT_FOUND`, the account is not enabled
for device authorization in that region.

## Identity file

Writes private `plaud-device.json` (mode `0600` on POSIX):

| Platform | Default path |
| --- | --- |
| All (source run) | `./data/plaud-device.json` |
| Override | `LOCALPLAUD_BLE__IDENTITY_PATH` or `--identity-path` |

**Never commit** this file. It holds binding token, signature, and RSA keys.

Regions: `platform-us.plaud.ai` (default), `platform-jp.plaud.ai`.

## Build the radio bridge

```bash
cd vendor/openplod-ble/plaud-bridge
cargo build --release
```

Set `LOCALPLAUD_BLE__BRIDGE_PATH` or place the binary on `PATH` / `./bin/`.
Source notice: `vendor/openplod-ble/NOTICE`.

## Enable the feature flag

```toml
[ble]
enabled = true
domain = "platform-us.plaud.ai"
```

Decoded BLE audio ingests with `source_transport=ble` and external id
`serial:sessionId` (Phase 3 dedupe). Live radio download additionally needs
identity + bridge; until hardware acceptance, treat transfer as experimental.

```bash
# After you have decoded audio on disk (fixture or successful download):
# use the ingest API / BleBackend.item_from_session path — see tests.
localplaud ble doctor --json
```

## Windows vs WSL (honest)

| Host | Reality |
| --- | --- |
| **Windows native** | Implemented first here (WinRT via `plaud-bridge`). Upstream OpenPlod built the bridge for Windows; **full Note Pro extraction on Windows is not verified**. |
| **WSL** | Bluetooth passthrough is limited/unreliable. Do **not** treat WSL as the acceptance path for Phase 4 hardware until proven. Prefer native Windows for provision/doctor on this machine, and Linux+BlueZ (non-WSL) for later acceptance. |
| **Linux (BlueZ)** | Preferred long-term acceptance target. Upstream verified discovery/connect; full download not recorded without a provisioned identity. |
| **Docker** | BLE unsupported in default containers. |

## Doctor / CLI

| Command | Purpose |
| --- | --- |
| `localplaud ble doctor` | Redacted readiness (flag, bridge, identity, ffmpeg) |
| `localplaud ble provision` | Paste token → Partner SDK → `plaud-device.json` |
| `localplaud ble scan` | Optional scan when bridge present (redacted) |
| `localplaud ble clear-identity --yes` | Delete local authorization |

Optional Python crypto: `pip install 'localplaud[ble]'` (ChaCha20 / RSA unwrap).

## Attribution

See root `NOTICE`, `ATTRIBUTION.md`, and `vendor/openplod-ble/NOTICE`.
OpenPlod MIT Copyright 2026 Remi Pelloux and contributors; openplaud inheritance
residual risk accepted by the owner for this selective adapter.
