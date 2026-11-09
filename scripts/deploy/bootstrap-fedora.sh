#!/usr/bin/env bash
#
# Fedora host bootstrap guidance for Plaud-local core.
# Installs nothing invasive by default: checks Docker/ffmpeg and prints the
# recommended next steps. Use --packages to install core dnf deps (not Docker
# itself — follow current Fedora Docker/podman docs for the engine).
#
# Usage:
#   ./scripts/deploy/bootstrap-fedora.sh
#   ./scripts/deploy/bootstrap-fedora.sh --packages
#   ./scripts/deploy/bootstrap-fedora.sh --ble-host   # also remind BlueZ deps
set -euo pipefail

WANT_PACKAGES=false
WANT_BLE_HINT=false
for arg in "$@"; do
  case "$arg" in
    --packages) WANT_PACKAGES=true ;;
    --ble-host) WANT_BLE_HINT=true ;;
    -h|--help)
      sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "error: unknown argument: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

log() { printf '==> %s\n' "$*"; }

if [ ! -f /etc/os-release ] || ! grep -qi fedora /etc/os-release; then
  log "warning: this helper targets Fedora; continuing with generic checks."
fi

if $WANT_PACKAGES; then
  if ! command -v dnf >/dev/null 2>&1; then
    echo "error: dnf not found; cannot install packages" >&2
    exit 1
  fi
  log "installing core packages (python tooling left to uv)"
  sudo dnf install -y git ffmpeg curl
fi

if command -v ffmpeg >/dev/null 2>&1; then
  log "ffmpeg: $(command -v ffmpeg)"
else
  log "ffmpeg: missing — install with: sudo dnf install -y ffmpeg"
fi

if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  log "Docker + compose: $(docker --version)"
  if ! docker info >/dev/null 2>&1; then
    log "Docker is installed but the daemon is not reachable — start it, then retry."
  fi
  if [ "$(id -u)" -ne 0 ] && ! id -nG "${USER:-}" 2>/dev/null | grep -qw docker; then
    log "hint: add ${USER:-you} to the docker group (new login required)"
  fi
else
  log "Docker Engine + compose plugin not detected."
  log "  Native path: docs/deploy-fedora.md (uv run localplaud run)"
  log "  Docker path: install Docker for Fedora, then:"
  log "    docker compose --profile core up -d --build"
fi

if $WANT_BLE_HINT; then
  log "BLE is experimental and unsupported in default containers."
  log "  Host packages: sudo dnf install -y bluez bluez-libs dbus ffmpeg"
  log "  Bridge binary: ./scripts/packaging/build-plaud-bridge.sh"
  log "  Details: docs/ble-host.md"
fi

log "done. Next:"
log "  docs/deploy-fedora.md          # native or Docker core"
log "  docs/deploy-fedora-igm.md      # IGM / ROCm client wiring"
log "  docs/platform-matrix.md        # honest OS matrix"
log "  # AMD hosts: do NOT use compose --profile gpu (NVIDIA/CUDA only)"
