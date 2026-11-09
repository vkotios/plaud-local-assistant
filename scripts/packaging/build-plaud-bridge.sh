#!/usr/bin/env bash
#
# Build the experimental plaud-bridge GATT helper when the Phase 4 vendor crate
# is present. Compile evidence ≠ Note Pro transfer evidence.
#
# Exit codes:
#   0  built successfully, or skipped because sources are not in this tree
#   1  sources present but the build failed
#
# Usage:
#   ./scripts/packaging/build-plaud-bridge.sh
#   PLAUD_BRIDGE_OUT=./bin ./scripts/packaging/build-plaud-bridge.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CRATE="${ROOT}/vendor/openplod-ble/plaud-bridge"
OUT_DIR="${PLAUD_BRIDGE_OUT:-${ROOT}/bin}"

log() { printf '==> %s\n' "$*"; }

if [ ! -f "${CRATE}/Cargo.toml" ]; then
  log "skipped: plaud-bridge crate not present at vendor/openplod-ble/plaud-bridge"
  log "        (core packaging is fine; BLE adapter lands with Phase 4)"
  log "        host requirements: docs/ble-host.md"
  exit 0
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "error: cargo not found; install a Rust toolchain to build plaud-bridge" >&2
  exit 1
fi

log "building plaud-bridge (release) from ${CRATE}"
(
  cd "${CRATE}"
  cargo build --release
)

built="${CRATE}/target/release/plaud-bridge"
if [ ! -x "${built}" ]; then
  # Windows MSVC / mingw may emit .exe
  if [ -f "${built}.exe" ]; then
    built="${built}.exe"
  else
    echo "error: expected binary missing after cargo build: ${built}" >&2
    exit 1
  fi
fi

mkdir -p "${OUT_DIR}"
cp -f "${built}" "${OUT_DIR}/"
log "installed $(basename "${built}") → ${OUT_DIR}/"
log "note: compile success is not hardware transfer acceptance (docs/ble-host.md)"
