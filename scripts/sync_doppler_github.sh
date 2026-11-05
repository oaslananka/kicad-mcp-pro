#!/usr/bin/env bash
# Selectively copy owner-approved keys from the only Doppler config (main).
set -euo pipefail

repo="oaslananka/kicad-mcp-pro"
project="kicad-mcp-pro"
config="main"

if [[ $# -lt 1 || $# -gt 2 || ( $# -eq 2 && "$2" != "--apply" ) ]]; then
  printf '%s\n' 'Usage: sync_doppler_github.sh GROUP [--apply]' >&2
  exit 2
fi

case "$1" in
  quality)
    names=(SONAR_TOKEN CODACY_PROJECT_TOKEN)
    destinations=(repository repository)
    ;;
  quality-extra)
    names=(CODECOV_TOKEN SEMGREP_APP_TOKEN)
    destinations=(repository repository)
    ;;
  live-eval)
    names=(NVIDIA_API_KEY OPENCODE_ZEN_API_KEY OPENAI_KEY)
    destinations=(live-model-evals live-model-evals repository)
    ;;
  release)
    names=(OASLANANKA_OPS_APP_PRIVATE_KEY)
    destinations=(repository)
    ;;
  gui)
    names=(TAURI_SIGNING_PRIVATE_KEY TAURI_SIGNING_PRIVATE_KEY_PASSWORD)
    destinations=(repository repository)
    ;;
  *)
    printf '%s\n' 'Unknown sync group (refusing arbitrary secret names)' >&2
    exit 2
    ;;
esac

if [[ $# -eq 1 ]]; then
  printf '%s\n' 'DRY RUN: no values fetched, no writes'
  for i in "${!names[@]}"; do
    printf '%s -> %s\n' "${names[$i]}" "${destinations[$i]}"
  done
  exit 0
fi

if [[ "${GITHUB_ACTIONS:-}" == "true" ]]; then
  printf '%s\n' 'ERROR: trusted operator device required' >&2
  exit 2
fi

# The exact repo and owner must match before touching any GitHub secret.
if [[ "$(gh api user --jq .login)" != "oaslananka" ]] \
    || [[ "$(gh api "repos/$repo" --jq .full_name)" != "$repo" ]]; then
  printf '%s\n' 'ERROR: authenticated GitHub account or repository mismatch' >&2
  exit 2
fi

# Complete the whole group's preflight before any writes; use only main.
# A sentinel keeps trailing newlines intact in shell command substitution;
# strip exactly the terminal newline added by the Doppler CLI.
values=()
for i in "${!names[@]}"; do
  key="${names[$i]}"
  if ! value="$(doppler secrets get "$key" --project "$project" --config "$config" \
          --plain --no-check-version --silent && printf '\036')"; then
    printf 'ERROR: missing or inaccessible value for %s\n' "$key" >&2
    exit 2
  fi
  value="${value%$'\036'}"
  value="${value%$'\n'}"
  if [[ -z "$value" || ${#value} -gt 65536 ]]; then
    printf 'ERROR: missing or invalid value for %s\n' "$key" >&2
    exit 2
  fi
  values+=("$value")
done

for i in "${!names[@]}"; do
  name="${names[$i]}"
  destination="${destinations[$i]}"
  if [[ "$destination" == "repository" ]]; then
    printf '%s' "${values[$i]}" | gh secret set "$name" --repo "$repo" --app actions
  else
    printf '%s' "${values[$i]}" | gh secret set "$name" --repo "$repo" --env "$destination"
  fi
  printf 'Synced %s -> %s\n' "$name" "$destination"
done