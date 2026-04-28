#!/usr/bin/env bash
set -euo pipefail

: "${DOPPLER_PROJECT:=all}"
: "${DOPPLER_CONFIG:=main}"

missing=()
while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^# ]] && continue
  if ! doppler secrets get "$line" --plain \
        --project "$DOPPLER_PROJECT" --config "$DOPPLER_CONFIG" \
        >/dev/null 2>&1; then
    missing+=("$line")
  fi
done < .doppler/secrets.txt

if [ "${#missing[@]}" -gt 0 ]; then
  printf 'Missing Doppler secrets in %s/%s:\n' "$DOPPLER_PROJECT" "$DOPPLER_CONFIG" >&2
  printf '  - %s\n' "${missing[@]}" >&2
  exit 1
fi

echo "All Doppler secrets present in ${DOPPLER_PROJECT}/${DOPPLER_CONFIG}."
