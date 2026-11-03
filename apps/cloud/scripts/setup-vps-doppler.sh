#!/usr/bin/env bash
# Fresh-VPS bootstrap only. Reads a read-only service token from the TTY;
# the CLI stores it in a directory-scoped configuration. No token on argv,
# in shell history, source code, GitHub logs or plaintext .env files.
set -euo pipefail
set +x
umask 077
if [[ $# -ne 2 || ! "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$ ||
      ! "$2" =~ ^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$ ]]; then
  echo 'Usage: bash scripts/setup-vps-doppler.sh PROJECT CONFIG' >&2
  exit 2
fi
if [[ ! -t 0 ]]; then
  echo 'Interactive owner TTY required; never pipe a token through a logged command' >&2
  exit 2
fi
if [[ -n "${DOPPLER_TOKEN:-}" || -n "${DOPPLER_PROJECT:-}" || -n "${DOPPLER_CONFIG:-}" ]]; then
  echo 'Unset existing Doppler token/project/config environment variables first' >&2
  exit 2
fi
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
command -v doppler >/dev/null || { echo 'Official Doppler CLI is required' >&2; exit 2; }
read -r -s -p 'Paste config-scoped, read-only VPS Doppler service token: ' token
printf '\n'
[[ -n "$token" ]] || { echo 'Empty token rejected' >&2; exit 2; }
# The service token exists only inside this short-lived shell and Doppler CLI
# config scope, never as a command-line argument or a project artifact.
DOPPLER_TOKEN="$token" doppler setup --no-interactive --project "$1" --config "$2" --scope "$root"
unset token
# The real runtime wrapper ignores ambient config selectors in scoped mode.
KICAD_DOPPLER_SCOPED=true scripts/doppler-runtime.sh node scripts/portable-config.mjs validate
printf 'Scoped Doppler setup and runtime configuration verified (values redacted).\n'
