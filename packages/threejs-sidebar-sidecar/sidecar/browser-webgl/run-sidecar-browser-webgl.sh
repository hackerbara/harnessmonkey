#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_BIN="$SCRIPT_DIR/dist/ThreeJsBrowserWebglSidecar.app/Contents/MacOS/laufey"
if [[ ! -x "$APP_BIN" ]]; then
  echo '{"type":"error","message":"browser-webgl app missing; run browser-webgl/build-browser-webgl.sh"}'
  exit 2
fi
export THREE_SIDECAR_BROWSER_WEBGL_ROOT="$SCRIPT_DIR"
export THREE_SIDECAR_BROWSER_WEBGL_ASSET_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
exec "$APP_BIN" "$@"
