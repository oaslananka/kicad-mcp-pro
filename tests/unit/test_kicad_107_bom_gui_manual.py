"""Review gates for the explicit, isolated KiCad 10.0.7 GUI BOM regression."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tests/gui/manual_kicad_107_bom_gui.sh"


def test_local_operator_probe_is_explicit_and_disposable() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.startswith("#!/usr/bin/env bash")
    assert "KICAD_BOM_GUI_OPERATOR=1" in source
    assert "${KICAD_BOM_GUI_OPERATOR:-}" in source
    assert "$(id -u) -ne 0" in source
    assert "xvfb-run -a -s '-screen 0 1440x900x24'" in source
    assert "mktemp -d /tmp/kicad-107-bom-operator-XXXXXXXX" in source
    assert "trap 'rm -rf -- \"$BOM_WORKSPACE\"' EXIT" in source
    assert 'export HOME="$workspace/home"' in source
    assert 'XDG_CONFIG_HOME="$workspace/home/.config"' in source
    assert "GDK_BACKEND=x11" in source
    assert "$(kicad-cli version)" in source
    assert "== '10.0.7'" in source
    assert "Unknown GUI window/modal detected: refusing all further interaction" in source
    assert "'Symbol Fields Table'" in source
    assert "# New KiCad profiles initially open on the Edit tab. Always select Export." in source
    assert '[[ "$observed" == "$STORED" ]]' in source
    assert '[[ "$observed" == "$CANCELLED" ]]' in source
    assert '[[ "$after" == "$before" ]]' in source
    assert "'cancelDiscarded': True" not in source  # observed checks, no fake pass variable
    assert '"cancelDiscarded":true' in source
    assert "wx.TheClipboard.GetData(data)" in source


def test_only_bundled_public_demo_is_copied_and_no_user_project_argument() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "/usr/share/kicad/demos/royalblue54L_feather/nfc_antenna/" in source
    assert '"$DEMO/$BASENAME.kicad_pro"' in source
    assert '"$DEMO/$BASENAME.kicad_sch"' in source
    assert "[[ $# -eq 0 ]]" in source
    assert "(profile / 'kicad_common.json').write_text(" in source
    assert "'enable_server': False" in source
    assert "'data_collection_prompt': True" in source
    assert '"$workspace/project/$CANCELLED"' in source
    assert '"$workspace/project/$STORED"' in source
    assert "--private-child" in source


def test_operator_consent_must_precede_native_gui_execution() -> None:
    """Static fail-closed review; never launch a GUI from normal unit pytest."""
    source = SCRIPT.read_text(encoding="utf-8")
    entrypoint = source.split("main() {", 1)[1]
    permission_gate = "[[ \"${KICAD_BOM_GUI_OPERATOR:-}\" == '1' ]] || fail"
    assert permission_gate in entrypoint
    assert entrypoint.index(permission_gate) < entrypoint.index("BOM_WORKSPACE=$(mktemp")
    assert "[[ $(id -u) -ne 0 ]]" in entrypoint
    assert "[[ $# -eq 0 ]]" in source
    assert "Requires deliberate KICAD_BOM_GUI_OPERATOR=1 opt-in" in source
    assert "Private child mode requires an operator-launched Xvfb session" in source
    assert "KICAD_BOM_GUI_PRIVATE_CHILD=1 xvfb-run" in source
    assert "Unknown GUI window/modal detected" in source


def test_no_automatic_workflow_starts_operator_gui() -> None:
    """Portable static policy, including Windows without a Bash installation."""
    workflows = ROOT / ".github/workflows"
    for workflow in workflows.glob("*.yml"):
        assert "manual_kicad_107_bom_gui.sh" not in workflow.read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    assert "#!/usr/bin/env bash" in source
    assert "set -Eeuo pipefail" in source
    assert "xvfb-run -a -s '-screen 0 1440x900x24'" in source
    assert "wx.TheClipboard.GetData(data)" in source
