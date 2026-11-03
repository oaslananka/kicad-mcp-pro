#!/usr/bin/env bash
# Wrap a single process with Doppler. Never persist or print fetched values.
set -euo pipefail
if [[ "${KICAD_DOPPLER_SCOPED:-false}" == true ]]; then
  # A token inherited from the shell silently overrides the CLI directory
  # scope and can select the wrong project/config (Doppler precedence).
  if [[ -n "${DOPPLER_TOKEN:-}" || -n "${DOPPLER_PROJECT:-}" || -n "${DOPPLER_CONFIG:-}" ]]; then
    echo 'Ambiguous Doppler selection: remove inherited token/project/config environment variables; use the directory-scoped CLI service token' >&2
    exit 2
  fi
  exec doppler run --no-read-env -- "$@"
fi
# Existing VPS retains its explicit selection; other operators can override
# with nonsecret bootstrap selectors. The secrets still come ONLY from Doppler.
project=${DOPPLER_PROJECT:-kicad-mcp-pro}
config=${DOPPLER_CONFIG:-prd_cloud}
exec doppler run -p "$project" -c "$config" -- "$@"
