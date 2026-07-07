#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DENO_BIN="${DENO_BIN:-/opt/homebrew/bin/deno}"
exec "$DENO_BIN" run -A --unstable-webgpu --node-modules-dir=auto "$SCRIPT_DIR/run-eidoverse-scene-sidecar.mjs" "$@"
