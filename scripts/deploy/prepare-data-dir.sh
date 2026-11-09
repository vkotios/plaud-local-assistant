#!/usr/bin/env bash
#
# Ensure ./data is writable by the Compose app user (Dockerfile USER uid 1000).
# Docker creates a missing bind-mount source as root on Linux, which then makes
# `localplaud run` fail with PermissionError on localplaud.db.schema.lock.
#
# Usage (from repo root, before compose up — same path as docs/deploy-fedora.md):
#   ./scripts/deploy/prepare-data-dir.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA="${ROOT}/data"

mkdir -p "${DATA}"

as_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    return 1
  fi
}

if as_root chown -R 1000:1000 "${DATA}"; then
  printf '==> data dir ready for container uid 1000: %s\n' "${DATA}"
else
  # Last-resort for environments without sudo (still better than root-owned empty dir).
  chmod -R a+rwX "${DATA}"
  printf '==> data dir made world-writable (could not chown 1000:1000): %s\n' "${DATA}"
fi
