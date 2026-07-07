#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if ! command -v deno >/dev/null 2>&1; then
  echo "deno not found; install Deno >= 2.9 first" >&2
  exit 127
fi
deno_version="$(deno --version | awk '/^deno /{print $2}')"
deno_major="${deno_version%%.*}"
deno_rest="${deno_version#*.}"
deno_minor="${deno_rest%%.*}"
if (( ${deno_major:-0} < 2 || ( ${deno_major:-0} == 2 && ${deno_minor:-0} < 9 ) )); then
  echo "deno desktop requires Deno >= 2.9; found ${deno_version:-unknown}" >&2
  exit 2
fi
export THREE_SIDECAR_BROWSER_WEBGL_ROOT="$SCRIPT_DIR"
export THREE_SIDECAR_BROWSER_WEBGL_ASSET_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
mkdir -p "$SCRIPT_DIR/dist"
cd "${TMPDIR:-/tmp}"
exec deno desktop -A --no-prompt --no-config --backend cef --output "$SCRIPT_DIR/dist/ThreeJsBrowserWebglSidecar.app" "$SCRIPT_DIR/main.ts"
