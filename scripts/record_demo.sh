#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
DEMO_CAST="${ROOT_DIR}/docs/assets/demo.cast"
DEMO_GIF="${ROOT_DIR}/docs/assets/demo.gif"

if ! command -v asciinema >/dev/null 2>&1; then
  echo "asciinema is required. Install it with your package manager or see https://docs.asciinema.org/manual/cli/installation/"
  exit 1
fi

if ! command -v agg >/dev/null 2>&1; then
  echo "agg is required. Install it with: cargo install --locked agg"
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it with: https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi

asciinema rec "${DEMO_CAST}" \
  --overwrite \
  --idle-time-limit 2 \
  --command "cd '${ROOT_DIR}' && uv run --all-extras python scripts/generate_synthetic_demo.py --playback"

agg --speed 1.2 --theme monokai --font-size 18 "${DEMO_CAST}" "${DEMO_GIF}"

if [[ "$(wc -c < "${DEMO_GIF}")" -gt $((2 * 1024 * 1024)) ]]; then
  echo "warning: docs/assets/demo.gif exceeded 2 MB; retrying with --font-size 14"
  agg --speed 1.2 --theme monokai --font-size 14 "${DEMO_CAST}" "${DEMO_GIF}"
fi
