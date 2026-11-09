# Fedora core deploy (Plaud-local)

**Primary operator OS:** Fedora/Linux. This is the one clean core install path for
Plaud-local v1. Choose **native** (recommended on AMD Strix Halo) or **Docker
`core`**. Windows is documented separately in [windows.md](windows.md).

Local text inference goes through **inference-gateway-manager (IGM)** — see
[deploy-fedora-igm.md](deploy-fedora-igm.md). Optional ASR/diarization extras:
[extras-matrix.md](extras-matrix.md). Platform overview:
[platform-matrix.md](platform-matrix.md).

> **Bluetooth is not part of the Docker core path.** Host requirements live in
> [ble-host.md](ble-host.md). Default containers refuse BLE (doctor fails loud).

## Option A — Native (recommended on Fedora / AMD)

```bash
sudo dnf install -y python3.12 python3.12-devel git ffmpeg curl
# Optional host BLE packages only if you will run experimental Note Pro transfer:
# sudo dnf install -y bluez bluez-libs dbus-devel   # see docs/ble-host.md

curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/vkotios/plaud-local-assistant.git
cd plaud-local-assistant

# Application + tooling. Prefer CPU ASR extras — never assume NVIDIA CUDA.
uv sync --extra dev --extra cloud --extra faster-whisper

cp config.example.toml config.toml
cp .env.example .env
# Edit config.toml / .env: [llm] provider = "ai-gateway" → IGM :9000/v1
# See docs/deploy-fedora-igm.md for the full IGM checklist.

uv run localplaud init
uv run localplaud auth login    # official Open API OAuth
uv run localplaud doctor        # ffmpeg, runtime=host/native, providers
uv run localplaud run           # sync + process + Web App on :8080
```

Optional HTTPS: terminate with host Caddy using
[`deploy/caddy/Caddyfile.host-native`](../deploy/caddy/Caddyfile.host-native)
(points at `127.0.0.1:8080`; IGM stays on the host).

## Option B — Docker `core` profile

Slim CPU image + Caddy. No CUDA. No BLE radio.

```bash
# Fedora: install Docker Engine + compose plugin (official docs), then:
./scripts/deploy/bootstrap-fedora.sh   # guidance + group membership checks

cp .env.example .env && $EDITOR .env           # DOMAIN, ACME_EMAIL, …
cp config.example.toml config.toml && $EDITOR config.toml

# Bind mount ./data → /app/data. The image runs as uid 1000; Docker creates a
# missing host path as root, which then PermissionError's on schema.lock.
./scripts/deploy/prepare-data-dir.sh

# Image CMD is `localplaud run` (needs /bin/ps via procps in the Dockerfile).
docker compose --profile core up -d --build
./scripts/deploy/smoke-test.sh http://127.0.0.1:8081
```

`cpu` is an alias of the same service (`--profile cpu` also works).

Reach IGM on the host from the container with
`http://host.docker.internal:9000/v1` (add `extra_hosts` if needed) or a LAN URL.
Do **not** start the Compose `gpu` profile on AMD-only machines.

### What Docker core does **not** include

| Capability | In `core` container? |
| --- | --- |
| Web App + poller + pipeline | Yes |
| Official Open API / file upload ingest | Yes |
| Local knowledge MCP | Run on host / sidecar (stdio) |
| NVIDIA CUDA ASR | No — use `gpu` only on NVIDIA hosts |
| AMD ROCm engines | No — use IGM on the host |
| Bluetooth Note Pro | **No** — see [ble-host.md](ble-host.md) |

## Doctor checks

```bash
uv run localplaud doctor
# Expect: runtime ✓ host/native   OR   runtime ✓ docker/container
# ble packaging ✓ … (fails if BLE enabled inside Docker)
```

## Updating

```bash
git pull
# Native:
uv sync --extra dev --extra cloud --extra faster-whisper
# Docker:
docker compose --profile core up -d --build
```
