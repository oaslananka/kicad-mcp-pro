#!/usr/bin/env bash
# Explicit operator-only, disposable KiCad 10.0.7 GUI regression (#24860).
# Run with KICAD_BOM_GUI_OPERATOR=1; NEVER invoke from PR/push CI or a user desktop.
set -Eeuo pipefail

readonly DEMO='/usr/share/kicad/demos/royalblue54L_feather/nfc_antenna/RoyalBlue54L-NFC-Antenna'
readonly BASENAME='RoyalBlue54L-NFC-Antenna'
readonly STORED='BOM_STORED_PROJECT_107.csv'
readonly CANCELLED='BOM_CANCEL_MUST_DISCARD_107.csv'

fail() { printf 'KiCad BOM GUI qualification failed: %s\n' "$*" >&2; exit 1; }

window_id() {
  local title="$1"
  xdotool search --onlyvisible --name "$title" 2>/dev/null | head -n 1 || true
}

wait_for_window() {
  local title="$1" id attempt
  for ((attempt=0; attempt<100; attempt++)); do
    id=$(window_id "$title")
    if [[ -n "$id" ]]; then printf '%s' "$id"; return 0; fi
    sleep 0.25
  done
  fail "Required editor window did not appear: $title"
}

check_visible_windows() {
  local id name
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    name=$(xdotool getwindowname "$id" 2>/dev/null || true)
    case "$name" in
      ''|"$BASENAME — KiCad 10.0"|"$BASENAME — Schematic Editor"|"*$BASENAME — Schematic Editor"|'Symbol Fields Table') ;;
      *) fail 'Unknown GUI window/modal detected: refusing all further interaction' ;;
    esac
  done < <(xdotool search --onlyvisible --name '.*' 2>/dev/null || true)
}

clipboard_text() {
  /usr/bin/python3 - <<'PY'
import wx
app = wx.App(False)
data = wx.TextDataObject()
if not wx.TheClipboard.Open():
    raise SystemExit('Cannot read isolated Xvfb clipboard')
try:
    if not wx.TheClipboard.GetData(data):
        raise SystemExit('Isolated clipboard has no text')
    print(data.GetText(), end='')
finally:
    wx.TheClipboard.Close()
PY
}

read_bom_field() {
  local dialog="$1"
  check_visible_windows
  xdotool mousemove --window "$dialog" 1030 67 click 1
  xdotool key --clearmodifiers ctrl+a
  xdotool key --clearmodifiers ctrl+c
  sleep 0.3
  clipboard_text
}

open_bom() {
  local schematic="$1"
  check_visible_windows
  [[ -z "$(window_id 'Symbol Fields Table')" ]] || fail 'Unexpected pre-existing BOM modal'
  xdotool mousemove --window "$schematic" 1165 46 click 1
  local dialog
  dialog=$(wait_for_window 'Symbol Fields Table')
  check_visible_windows
  # New KiCad profiles initially open on the Edit tab. Always select Export.
  xdotool mousemove --window "$dialog" 515 25 click 1
  sleep 1
  printf '%s' "$dialog"
}

cancel_bom() {
  local dialog="$1"
  check_visible_windows
  xdotool mousemove --window "$dialog" 1292 691 click 1
  sleep 1
  [[ -z "$(window_id 'Symbol Fields Table')" ]] || fail 'BOM Cancel did not close the dialog'
}

run_qualified_gui() {
  local workspace="$1" project="$1/project/$BASENAME.kicad_pro"
  local before after manager schematic dialog observed
  export HOME="$workspace/home" XDG_CONFIG_HOME="$workspace/home/.config"
  export XDG_CACHE_HOME="$workspace/home/.cache" XDG_DATA_HOME="$workspace/home/.local/share"
  export GDK_BACKEND=x11
  [[ -n "${DISPLAY:-}" ]] || fail 'A private Xvfb DISPLAY is required'
  [[ "$(kicad-cli version)" == '10.0.7' ]] || fail 'Only native KiCad 10.0.7 is qualified'
  before=$(sha256sum "$project" | cut -d ' ' -f 1)
  kicad "$project" > "$workspace/manager.log" 2>&1 &
  BOM_MANAGER_PID=$!
  trap 'kill "$BOM_MANAGER_PID" 2>/dev/null || true; wait "$BOM_MANAGER_PID" 2>/dev/null || true' EXIT
  manager=$(wait_for_window "$BASENAME.*KiCad")
  check_visible_windows
  xdotool mousemove --window "$manager" 345 52 click --repeat 2 --delay 160 1
  schematic=$(wait_for_window "$BASENAME.*Schematic Editor")
  # The window is mapped before the native schematic document has loaded.
  sleep 6
  check_visible_windows
  dialog=$(open_bom "$schematic")
  observed=$(read_bom_field "$dialog")
  [[ "$observed" == "$STORED" ]] || fail "BOM saved filename mismatch (observed: ${observed@Q})"

  xdotool key --clearmodifiers ctrl+a
  xdotool type --clearmodifiers --delay 2 "$CANCELLED"
  observed=$(read_bom_field "$dialog")
  [[ "$observed" == "$CANCELLED" ]] || fail 'BOM field was not actually edited'
  cancel_bom "$dialog"
  after=$(sha256sum "$project" | cut -d ' ' -f 1)
  [[ "$after" == "$before" ]] || fail 'Cancel unexpectedly changed the project file'

  dialog=$(open_bom "$schematic")
  observed=$(read_bom_field "$dialog")
  [[ "$observed" == "$STORED" ]] || fail 'Cancelled filename was retained when the dialog reopened'
  cancel_bom "$dialog"
  after=$(sha256sum "$project" | cut -d ' ' -f 1)
  [[ "$after" == "$before" ]] || fail 'Project file changed after reopening and cancelling'
  [[ ! -e "$workspace/project/$CANCELLED" ]] || fail 'Cancelled BOM filename was exported'
  [[ ! -e "$workspace/project/$STORED" ]] || fail 'BOM file was created without Export'
  printf '%s\n' '{"schemaVersion":"kicad-107-bom-gui.v1","kicadVersion":"10.0.7","status":"pass","storedFilenameRead":true,"cancelDiscarded":true,"reopenedOriginalFilename":true,"projectSha256Unchanged":true,"scope":"operator-only Linux Xvfb GUI"}'
}

main() {
  [[ "${KICAD_BOM_GUI_OPERATOR:-}" == '1' ]] || fail 'Requires deliberate KICAD_BOM_GUI_OPERATOR=1 opt-in'
  [[ $(id -u) -ne 0 ]] || fail 'Never execute this GUI probe as root'
  [[ -x /usr/bin/python3 ]] || fail 'Apt Python with wxWidgets is required'
  for executable in kicad kicad-cli xvfb-run xdotool sha256sum; do
    command -v "$executable" >/dev/null || fail "Required Linux tool missing: $executable"
  done
  [[ "$(kicad-cli version)" == '10.0.7' ]] || fail 'Exact KiCad 10.0.7 required'
  [[ -f "$DEMO/$BASENAME.kicad_pro" && -f "$DEMO/$BASENAME.kicad_sch" ]] || fail 'Official single-root KiCad demo not installed'
  local workspace
  BOM_WORKSPACE=$(mktemp -d /tmp/kicad-107-bom-operator-XXXXXXXX)
  workspace=$BOM_WORKSPACE
  trap 'rm -rf -- "$BOM_WORKSPACE"' EXIT
  mkdir -p "$workspace/project" "$workspace/home/.config/kicad/10.0"
  cp "$DEMO/$BASENAME.kicad_pro" "$DEMO/$BASENAME.kicad_sch" "$workspace/project/"
  /usr/bin/python3 - "$workspace" "$STORED" <<'PY'
import json
from pathlib import Path
import shutil
import sys
workspace, filename = Path(sys.argv[1]), sys.argv[2]
project = workspace / 'project/RoyalBlue54L-NFC-Antenna.kicad_pro'
content = json.loads(project.read_text())
content['schematic']['bom_export_filename'] = filename
project.write_text(json.dumps(content, indent=2) + '\n')
profile = workspace / 'home/.config/kicad/10.0'
(profile / 'kicad_common.json').write_text(json.dumps({
    'api': {'enable_server': False},
    'graphics': {'canvas_type': 2},
    'do_not_show_again': {
        'update_check_prompt': True,
        'data_collection_prompt': True,
    },
}, indent=2))
for table in ('sym-lib-table', 'fp-lib-table'):
    shutil.copy2(Path('/usr/share/kicad/template') / table, profile / table)
source = Path('/usr/share/kicad/template/design-block-lib-table')
if source.is_file():
    shutil.copy2(source, profile / source.name)
else:
    (profile / 'design-block-lib-table').write_text('(design_block_lib_table (version 7))\n')
PY
  KICAD_BOM_GUI_PRIVATE_CHILD=1 xvfb-run -a -s '-screen 0 1440x900x24' bash "$0" --private-child "$workspace"
}

if [[ "${1:-}" == '--private-child' ]]; then
  [[ "${KICAD_BOM_GUI_PRIVATE_CHILD:-}" == '1' && "${KICAD_BOM_GUI_OPERATOR:-}" == '1' ]] || fail 'Private child mode requires an operator-launched Xvfb session'
  [[ -d "${2:-}" && "${2:-}" == /tmp/kicad-107-bom-operator-* ]] || fail 'Private scratch workspace missing'
  run_qualified_gui "$2"
else
  [[ $# -eq 0 ]] || fail 'This manual-only probe takes no project paths or arbitrary commands'
  main
fi
