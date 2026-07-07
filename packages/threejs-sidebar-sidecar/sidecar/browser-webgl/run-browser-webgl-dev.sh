#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! command -v deno >/dev/null 2>&1; then
  echo '{"type":"error","message":"deno not found; install Deno >= 2.9"}'
  exit 127
fi
export THREE_SIDECAR_BROWSER_WEBGL_ROOT="$SCRIPT_DIR"
export THREE_SIDECAR_BROWSER_WEBGL_ASSET_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Deno Desktop HMR has shown EPERM when launched with cwd inside this package.
# Launch from a neutral cwd and pass an absolute script path.
cd "${TMPDIR:-/tmp}"
exec deno desktop -A --no-prompt --no-config --hmr --backend cef "$SCRIPT_DIR/main.ts" "$@"
