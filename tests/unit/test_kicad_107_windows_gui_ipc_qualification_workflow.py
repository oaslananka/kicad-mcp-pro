"""Manual-only isolated Windows 10.0.7 GUI/IPC qualification contract."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kicad-10-0-7-windows-gui-ipc-qualification.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_manual_only_with_disposable_windows_runner() -> None:
    wf = _workflow()
    assert wf[True] == {"workflow_dispatch": None}  # PyYAML YAML 1.1 treats 'on' as True.
    assert wf["permissions"] == {"contents": "read"}
    assert len(wf["jobs"]) == 1
    job = wf["jobs"]["windows-107-gui-ipc"]
    assert job["runs-on"] == "windows-2025"
    assert job["timeout-minutes"] <= 60
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_signed_official_installer_and_version_required_before_gui() -> None:
    steps = _workflow()["jobs"]["windows-107-gui-ipc"]["steps"]
    codes = [s.get("run", "") for s in steps]
    assert any("kicad-downloads.s3.cern.ch" in c for c in codes)
    signer = next(c for c in codes if "Get-AuthenticodeSignature" in c)
    assert "$signature.Status -ne 'Valid'" in signer
    assert "Unexpected KiCad Authenticode signer" in signer
    install = next(c for c in codes if "Isolated CLI missing" in c)
    assert "Wrong KiCad CLI version" in install
    assert "Device.kicad_sym" in install
    assert "kicad-107-native-install" in install


def test_actual_gui_enabled_and_missing_ipc_never_passes() -> None:
    steps = _workflow()["jobs"]["windows-107-gui-ipc"]["steps"]
    prepare = next(s["run"] for s in steps if s["name"].startswith("Prepare isolated"))
    smoke = next(s["run"] for s in steps if s["name"].startswith("Exercise real"))
    cleanup = next(s["run"] for s in steps if s["name"].startswith("Remove installer"))
    assert "KICAD_CONFIG_HOME" in prepare
    assert "'10.0'" in prepare
    assert "kicad_common.json" in prepare and "enable_server = $true" in prepare
    assert "pcbnew.exe" in prepare
    assert "KICAD_MCP_ENABLE_GUI_SMOKE=1" in prepare
    assert "KICAD_MCP_GUI_SMOKE_REQUIRED=1" in prepare
    assert "test_kicad_gui_live_context.py" in smoke
    assert "if ($exit -ne 0)" in smoke
    assert "$skips.Count -ne 0" in smoke
    assert "$cases.Count -ne 2" in smoke
    assert "verdict = 'pass'" in smoke
    assert "kicad-107-config" in cleanup
    assert "kicad-107-native-install" in cleanup
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["path"].endswith("/summary.json")
    assert steps[-1]["if"] == "always()"
