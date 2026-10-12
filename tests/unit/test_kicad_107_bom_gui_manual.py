"""Review gates for the explicit, isolated KiCad 10.0.7 GUI BOM regression."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_native_gui_probe_cannot_run_without_operator_approval() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is not installed on this host")
    environment = os.environ.copy()
    environment.pop("KICAD_BOM_GUI_OPERATOR", None)
    result = subprocess.run(
        [bash, str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
        env=environment,
        check=False,
    )
    assert result.returncode != 0
    assert "Requires deliberate KICAD_BOM_GUI_OPERATOR=1 opt-in" in result.stderr
    assert '"status":"pass"' not in result.stdout


def test_shell_syntax_and_workflows_stay_separate() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is not installed on this host")
    subprocess.run([bash, "-n", str(SCRIPT)], check=True, timeout=10)
    workflows = ROOT / ".github/workflows"
    for workflow in workflows.glob("*.yml"):
        assert "manual_kicad_107_bom_gui.sh" not in workflow.read_text(encoding="utf-8")
