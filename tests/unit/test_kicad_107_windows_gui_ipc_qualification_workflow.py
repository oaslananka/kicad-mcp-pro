"""Manual-only isolated Windows 10.0.7 GUI/IPC qualification contract."""

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kicad-10-0-7-windows-gui-ipc-qualification.yml"


def _workflow() -> dict[str | bool, Any]:
    return cast(dict[str | bool, Any], yaml.safe_load(WORKFLOW.read_text(encoding="utf-8")))


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
    assert "KICAD_107_FIRST_RUN_TABLES_READY=true" in prepare
    assert "KICAD_107_FIRST_RUN_TABLES_READY -ne 'true'" in smoke
    assert "share/kicad/template" in prepare
    assert "share/kicad/symbols" in prepare
    assert "share/kicad/footprints" in prepare
    assert "sym-lib-table" in prepare and "fp-lib-table" in prepare
    assert "Copy-Item -LiteralPath $source -Destination $destination" in prepare
    assert "Get-FileHash -LiteralPath $destination -Algorithm SHA256" in prepare
    assert "KICAD10_TEMPLATE_DIR=$templateRoot" in prepare
    assert "KICAD10_FOOTPRINT_DIR=$footprintRoot" in prepare
    assert "KICAD10_SYMBOL_DIR=$symbolRoot" in prepare
    assert "KICAD_GUI_SMOKE_ARTIFACTS" in smoke
    assert "editor-readiness.json" in smoke
    assert "editorReadiness = $editor" in smoke
    assert "windowCount" in smoke and "standardDialogWindowCount" in smoke
    assert "Get-Content -LiteralPath $diag" in smoke
    assert 'throw "Signed isolated installation is missing standard $tableName"' in prepare
    assert "KICAD_GUI_SMOKE_PCB_ONLY=1" in prepare
    assert "Get-Process -Name explorer" in prepare
    assert "[Environment]::UserInteractive" in prepare
    assert "test_kicad_gui_live_context.py" in smoke
    assert "$accepted = (" in smoke
    assert "if (-not $accepted)" in smoke
    assert "$skips.Count -eq 0" in smoke
    assert "verdict = $verdict" in smoke
    assert "sessionZero" in smoke
    assert "explorerPresent" in smoke
    assert "$cases.Count -eq 2" in smoke
    assert "if ($accepted) { 'pass' } else { 'fail' }" in smoke
    assert "kicad-107-config" in cleanup
    assert "kicad-107-native-install" in cleanup
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 7
    assert upload["with"]["path"].endswith("/summary.json")
    assert steps[-1]["if"] == "always()"


def test_gui_single_pcb_editor_mode_is_explicit_and_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.gui import test_kicad_gui_live_context as smoke

    monkeypatch.delenv("KICAD_GUI_SMOKE_PCB_ONLY", raising=False)
    assert smoke._launch_auxiliary_editors() is True
    monkeypatch.setenv("KICAD_GUI_SMOKE_PCB_ONLY", "1")
    assert smoke._launch_auxiliary_editors() is False
    monkeypatch.setenv("KICAD_GUI_SMOKE_PCB_ONLY", "0")
    assert smoke._launch_auxiliary_editors() is True


def test_editor_snapshot_on_non_windows_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.gui import test_kicad_gui_live_context as smoke

    class FakeProcess:
        pid = 42

        def poll(self) -> int | None:
            return None

    monkeypatch.setattr("platform.system", lambda: "Linux")
    editor = smoke.ManagedProcess("pcb", cast(Any, FakeProcess()), ROOT)
    result = smoke._editor_readiness_snapshot(editor)
    assert result["processRunning"] is True
    assert result["processExitCode"] is None
    assert result["windowCount"] == 0
    assert "pid" not in result
    assert "title" not in result
