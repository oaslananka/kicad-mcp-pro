#!/usr/bin/env bash
# Install the reviewed, pinned KiCad 10.0.6 CLI without a mutable PPA.
set -euo pipefail

readonly archive_name='kicad-10.0.6-x86_64-lite.AppImage.tar'
readonly appimage_name='kicad-10.0.6-x86_64-lite.AppImage'
readonly archive_sha256='8c789e36644856cff30a66801692881582b9ca7c7475699494e614ce1bcb1f9c'
readonly appimage_sha256='806e949cb357f9f0a05c3298c36eecb2b06d79c0a36e12c99f75aad9c89f0792'
readonly base_url='https://mirrors.mit.edu/kicad/appimage/stable'
readonly install_root="${RUNNER_TEMP:?RUNNER_TEMP is required}/kicad-10-0-6-appimage"

mkdir -p "$install_root/bin"
archive="$install_root/$archive_name"
if [[ -n "${KICAD10_ARCHIVE_SOURCE_FILE:-}" ]]; then
  # Reuse a local fixture for isolated CI-installer acceptance. Hash checks
  # remain mandatory and this override must not be set by production CI.
  cp -- "$KICAD10_ARCHIVE_SOURCE_FILE" "$archive"
else
  curl --fail --location --retry 3 --retry-delay 2 \
    --connect-timeout 15 --max-time 240 --proto '=https' --tlsv1.2 \
    --output "$archive" "$base_url/$archive_name"
fi

printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum --check --status || {
  echo 'Pinned KiCad 10.0.6 archive SHA-256 mismatch; refusing execution.' >&2
  exit 1
}

# Extract only the exact expected archive member; never trust arbitrary paths.
if [[ "$(tar -tf "$archive")" != "$appimage_name" ]]; then
  echo 'Unexpected KiCad AppImage tar member list; refusing extraction.' >&2
  exit 1
fi
tar --no-same-owner --no-same-permissions -xf "$archive" -C "$install_root"
appimage="$install_root/$appimage_name"
printf '%s  %s\n' "$appimage_sha256" "$appimage" | sha256sum --check --status || {
  echo 'Pinned KiCad 10.0.6 AppImage SHA-256 mismatch; refusing execution.' >&2
  exit 1
}
chmod 0755 "$appimage"
(cd "$install_root" && "$appimage" --appimage-extract >/dev/null)

appdir="$install_root/AppDir"
if [[ ! -x "$appdir/AppRun" || ! -d "$appdir/usr/share/kicad/symbols/Device.kicad_symdir" \
      || ! -d "$appdir/usr/share/kicad/footprints/Resistor_SMD.pretty" ]]; then
  echo 'Pinned KiCad 10.0.6 CLI, symbols, or footprints are unavailable.' >&2
  exit 1
fi

cat > "$install_root/bin/kicad-cli" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "$script_dir/../AppDir/AppRun" kicad-cli "$@"
EOF
chmod 0755 "$install_root/bin/kicad-cli"
cli="$install_root/bin/kicad-cli"
if [[ "$($cli version)" != '10.0.6' ]]; then
  echo 'Bundled KiCad CLI version is not exactly 10.0.6.' >&2
  exit 1
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$install_root/bin" >> "$GITHUB_PATH"
fi
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'KICAD_CANARY_KICAD_CLI=%s\n' "$cli" >> "$GITHUB_ENV"
fi
printf 'Verified pinned KiCad 10.0.6 CLI: %s\n' "$cli"
