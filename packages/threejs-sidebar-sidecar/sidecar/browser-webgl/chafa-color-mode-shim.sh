#!/usr/bin/env bash
set -euo pipefail

CHAFA_BIN="${THREE_SIDECAR_REAL_CHAFA_BIN:-/opt/homebrew/bin/chafa}"
COLOR_MODE="${THREE_SIDECAR_CHAFA_COLORS:-256}"

args=()
skip_next=0
for arg in "$@"; do
  if [[ "$skip_next" == "1" ]]; then
    args+=("$COLOR_MODE")
    skip_next=0
    continue
  fi
  case "$arg" in
    -c|--colors)
      args+=("$arg")
      skip_next=1
      ;;
    -cfull)
      args+=("-c" "$COLOR_MODE")
      ;;
    --colors=*)
      args+=("--colors=$COLOR_MODE")
      ;;
    *)
      args+=("$arg")
      ;;
  esac
done

exec "$CHAFA_BIN" "${args[@]}"
