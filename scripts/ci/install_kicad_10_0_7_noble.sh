#!/usr/bin/env bash
# Install reviewed, SHA-256 pinned current-stable KiCad 10.0.7 CLI and matching symbols.
set -euo pipefail

readonly archive_name='kicad-10.0.7-x86_64-lite.AppImage.tar'
readonly appimage_name='kicad-10.0.7-x86_64-lite.AppImage'
readonly archive_sha256='3c6067b03e2e6eb7b3e17f63f6d57c2937a19c39d585edd0c0a8d0bebaec8969'
readonly appimage_sha256='05855274adb8eb7164ab886cfbbe8da7dd84f961d6d04783b66ffcb5011287cd'
readonly base_url='https://mirrors.mit.edu/kicad/appimage/stable'
readonly symbols_commit='1b2b42d49bc41559e43f590b084e7fe8f1e7f5fc'
readonly symbols_archive_sha256='2c6c52d300ac8f0ddaf750b301e2ad0396946b2b3417c01114a5be26e77bc3df'
readonly symbols_archive="kicad-symbols-${symbols_commit}.tar.gz"
readonly symbols_url="https://gitlab.com/kicad/libraries/kicad-symbols/-/archive/${symbols_commit}/${symbols_archive}"
readonly install_root="${RUNNER_TEMP:?RUNNER_TEMP is required}/kicad-10-0-7-appimage"

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
  echo 'Pinned KiCad 10.0.7 archive SHA-256 mismatch; refusing execution.' >&2
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
  echo 'Pinned KiCad 10.0.7 AppImage SHA-256 mismatch; refusing execution.' >&2
  exit 1
}
chmod 0755 "$appimage"
(cd "$install_root" && "$appimage" --appimage-extract >/dev/null)

appdir="$install_root/AppDir"
if [[ ! -x "$appdir/AppRun" || ! -d "$appdir/usr/share/kicad/symbols/Device.kicad_symdir" \
      || ! -d "$appdir/usr/share/kicad/footprints/Resistor_SMD.pretty" ]]; then
  echo 'Pinned KiCad 10.0.7 CLI, symbols, or footprints are unavailable.' >&2
  exit 1
fi

# KiCad 10 ships the official symbols in unpacked .kicad_symdir form.
# The existing kicad-sch-api symbol cache expects packed .kicad_sym files.
# Use the official symbols tag and its unmodified upstream CMake packer,
# rather than substituting old symbols or writing a divergent converter.
symbols_tar="$install_root/$symbols_archive"
if [[ -n "${KICAD10_SYMBOL_ARCHIVE_SOURCE_FILE:-}" ]]; then
  cp -- "$KICAD10_SYMBOL_ARCHIVE_SOURCE_FILE" "$symbols_tar"
else
  curl --fail --location --retry 3 --retry-delay 2 \
    --connect-timeout 15 --max-time 180 --proto '=https' --tlsv1.2 \
    --output "$symbols_tar" "$symbols_url"
fi
printf '%s  %s\n' "$symbols_archive_sha256" "$symbols_tar" | sha256sum --check --status || {
  echo 'Pinned KiCad 10.0.7 symbols SHA-256 mismatch; refusing to build.' >&2
  exit 1
}
mkdir -p "$install_root/symbols-src"
tar --no-same-owner --no-same-permissions -xzf "$symbols_tar" -C "$install_root/symbols-src"
symbols_root="$install_root/symbols-src/kicad-symbols-$symbols_commit"
cmake -S "$symbols_root" -B "$install_root/symbols-build" -DKICAD_PACK_SYM_LIBRARIES=ON
cmake --build "$install_root/symbols-build" --target pack_symbols --parallel 2
symbols_dir="$install_root/symbols-build/packed"
if [[ ! -s "$symbols_dir/Device.kicad_sym" || ! -s "$symbols_dir/Connector.kicad_sym" ]]; then
  echo 'Packing the version-pinned KiCad 10.0.7 symbol libraries failed.' >&2
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
if [[ "$($cli version)" != '10.0.7' ]]; then
  echo 'Bundled KiCad CLI version is not exactly 10.0.7.' >&2
  exit 1
fi

if [[ -n "${GITHUB_PATH:-}" ]]; then
  printf '%s\n' "$install_root/bin" >> "$GITHUB_PATH"
fi
if [[ -n "${GITHUB_ENV:-}" ]]; then
  printf 'KICAD_CANARY_KICAD_CLI=%s\n' "$cli" >> "$GITHUB_ENV"
  printf 'KICAD_SYMBOL_DIR=%s\n' "$symbols_dir" >> "$GITHUB_ENV"
  # The internal schematic connectivity comparator uses KiCadMCPConfig,
  # not kicad-sch-api's separate KICAD_SYMBOL_DIR discovery mechanism.
  printf 'KICAD_MCP_SYMBOL_LIBRARY_DIR=%s\n' "$symbols_dir" >> "$GITHUB_ENV"
  printf 'KICAD10_SYMBOL_DIR=%s\n' "$symbols_dir" >> "$GITHUB_ENV"
fi
printf 'Verified pinned KiCad 10.0.7 CLI: %s\n' "$cli"
