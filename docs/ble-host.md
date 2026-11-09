# Bluetooth host requirements (experimental)

Plaud-local’s Note Pro path is an **isolated experimental adapter** (Phase 4).
This document covers **host packaging only** — BlueZ, D-Bus, the `plaud-bridge`
binary, and ffmpeg. Partner provision / protocol / transfer: [ble.md](ble.md).

**Status:** experimental / **not GA**. Live BLE authorize/download is
**deferred** (Partner SDK blocked for the tested account — see [ble.md](ble.md)).
Supported recording ingest for now is **official Open API** cloud poll/download
(`localplaud auth login`). Linux full BLE download remains **Not verified**.
macOS scan/bridge was proven in Phase 4 live tests; default Docker images do
**not** ship BLE.

## Platform posture

| Runtime | BLE radio | Guidance |
| --- | --- | --- |
| Fedora/Linux host | BlueZ + D-Bus | Intended long-term host; keep experimental until acceptance |
| macOS host | CoreBluetooth | Preferred for first live hardware |
| Windows native | WinRT (if bridge present) | Secondary; hardware **Not verified** |
| WSL2 | Passthrough unreliable | Not an acceptance path |
| Docker / Podman default | **Unsupported** | Core file import / Open API only; doctor fails if BLE enabled |

Published matrix: [platform-matrix.md](platform-matrix.md). Windows policy:
[windows.md](windows.md).

## Host packages (Fedora)

```bash
sudo dnf install -y bluez bluez-libs dbus dbus-devel ffmpeg
sudo systemctl enable --now bluetooth
# Confirm the adapter is powered:
bluetoothctl show
```

Also required for a working radio path once the adapter lands:

| Component | Role |
| --- | --- |
| BlueZ | Linux Bluetooth stack |
| D-Bus | Session/system bus for BlueZ clients |
| `plaud-bridge` | Isolated Rust GATT helper (btleplug); build from the BLE vendor crate when present |
| ffmpeg / ffprobe | Decode/convert after a successful download |

## Build `plaud-bridge` (when the crate is in-tree)

Phase 4 vendors `vendor/openplod-ble/plaud-bridge`. On trees that include it:

```bash
./scripts/packaging/build-plaud-bridge.sh
# or:
#   cd vendor/openplod-ble/plaud-bridge && cargo build --release
```

Install the binary somewhere on `PATH`, under `./bin/`, or set
`LOCALPLAUD_BLE__BRIDGE_PATH`.

On trees **without** the vendor crate (main before Phase 4 merges), the packaging
script exits 0 and prints `skipped: plaud-bridge crate not present`. That is
intentional — compile evidence in CI is not transfer evidence, and missing
sources must not fail core packaging.

## Docker: loud refusal

Compose sets `LOCALPLAUD_RUNTIME=docker` on app services. `localplaud doctor`
reports:

- `runtime` → `docker/container`
- `ble packaging` → **fail** if `LOCALPLAUD_BLE__ENABLED=true` (or `[ble] enabled`)

There is **no** supported compose profile that mounts host BlueZ into the default
images. Run the Web App in Docker if you want; keep BLE on the host (or skip BLE).

## Doctor / smoke

```bash
# Host
uv run localplaud doctor

# Inside a core container (expect ble packaging ok only while BLE stays disabled)
docker compose --profile core exec localplaud-cpu localplaud doctor
```

Compile CI ≠ hardware transfer. A green `plaud-bridge` build job proves the
crate compiles on that runner OS; it does **not** prove Note Pro download.

## Out of scope here

- Partner `gen-key` / `sn-sign` / `plaud-device.json` provision flow
- Protocol 20 frame formats and session crypto
- Obsidian export
- Private / reverse-engineered Plaud sync APIs (permanently rejected)
