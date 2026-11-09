# Windows 11 support policy (Plaud-local v1)

Native Windows is **not** a first-class localplaud host. Plaud-local v1 supports
Windows 11 operators through **WSL2** (Fedora or Ubuntu) and/or **Docker Desktop**,
optionally with a **remote worker** for heavy stages. This matches the published
[platform matrix](platform-matrix.md) and Phase 0 evidence classes.

## Supported (v1)

| Path | Core app | BLE | Notes |
| --- | --- | --- | --- |
| WSL2 (Fedora/Ubuntu) | Yes — follow [deploy-fedora.md](deploy-fedora.md) inside WSL | Not an acceptance path | Prefer for daily core use |
| Docker Desktop | Yes — `docker compose --profile core …` | **Not supported** | Same loud BLE refusal as Linux containers |
| Remote worker from a Fedora controller | Yes (worker API) | N/A | See [remote-worker.md](remote-worker.md) |

## Not promised

- Native Windows install of the localplaud Web App / daemon as a supported product path.
- WinRT Bluetooth Note Pro download as verified hardware acceptance (upstream
  bridge code may exist; **live extraction Not verified**).
- WSL Bluetooth passthrough for Note Pro (unreliable; doctor warns if BLE is
  requested under WSL).

## Recommended layout

```
Windows 11
  └─ WSL2 Fedora/Ubuntu
       ├─ Plaud-local core (native uv OR Docker core profile)
       └─ optional: point [llm] at IGM on a Fedora/AMD box (LAN / Tailscale)
```

For AMD Strix Halo inference, run IGM on the Linux host that owns the GPU; the
Windows/WSL core is an OpenAI-compatible **client** only
([deploy-fedora-igm.md](deploy-fedora-igm.md)).

## BLE on Windows

If you experiment with Note Pro radio tooling from a Phase 4 tree:

- Prefer **macOS** for first live hardware acceptance (owner preference).
- Native WinRT is secondary and remains experimental until acceptance evidence.
- Do not enable BLE inside Docker Desktop containers — see [ble-host.md](ble-host.md).

## Evidence classes (do not inflate)

| Claim | Status |
| --- | --- |
| Core runs under WSL2/Docker | Packaging target (this doc) |
| Native Win localplaud | **Not supported** |
| WinRT Note Pro full download | **Not verified** |
| WSL BLE download | **Not verified** / unreliable |
