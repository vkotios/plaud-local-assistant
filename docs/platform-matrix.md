# Platform matrix (Plaud-local)

Published packaging matrix for operators. Evidence classes match the Phase 0/1
executive report — do not inflate “Yes” into verified live BLE download.

| Platform | Core app | BLE | Notes |
| --- | --- | --- | --- |
| Fedora/Linux | Yes (native/Docker) | Host BlueZ; full download **Not verified** upstream | **Primary target** |
| Docker | Yes (`core` / `cpu` / `gpu` / `mac` profiles) | **Not supported** by default | File import + Open API only |
| Windows 11 | WSL2 / remote-worker | WinRT code exists upstream; hardware **Not verified** | No native localplaud path |
| macOS | Yes | Strongest upstream BLE evidence | Not the Strix Halo host |

## Inference on AMD Strix Halo

- Point LLM stages at **inference-gateway-manager (IGM)** (`/v1`, concurrency 1,
  HTTP 409 busy). ROCm/HIP engines live in IGM — not in this repository.
- Do **not** use the Compose `gpu` (NVIDIA/CUDA) profile on AMD-only hosts.
- See [deploy-fedora.md](deploy-fedora.md), [deploy-fedora-igm.md](deploy-fedora-igm.md),
  and [extras-matrix.md](extras-matrix.md).

## Related packaging docs

| Doc | Purpose |
| --- | --- |
| [deploy-fedora.md](deploy-fedora.md) | Clean Fedora core install (native **or** Docker) |
| [windows.md](windows.md) | Windows 11 WSL2 / remote-worker policy |
| [ble-host.md](ble-host.md) | Host BLE requirements (BlueZ, D-Bus, bridge, ffmpeg) |
| [deploy.md](deploy.md) | Upstream compose profiles and operations |

## Evidence honesty

- Compose CI smoke proves **core** container health, not BLE transfer.
- Building `plaud-bridge` in CI (when the crate is present) is **compile**
  evidence only — it is not Note Pro download acceptance.
- Live hardware BLE remains **experimental** until an acceptance report lands
  (prefer macOS for first live radio; Linux/WSL secondary).
