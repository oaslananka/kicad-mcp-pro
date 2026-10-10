"""Guard the opt-in macOS 10.0.7 genuine GUI/IPC qualification lane.

A passing CLI-only probe must never be mislabeled as real PCB Editor IPC.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kicad-10-0-7-macos-gui-ipc-qualification.yml"


def _workflow() -> dict[str, object]:
    # PyYAML safe_load treats the GitHub Actions on key as YAML 1.1 True.
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_opt_in_macos_runner_has_readonly_permissions_and_no_pr_trigger() -> None:
    data = _workflow()
    assert data[True] == {"workflow_dispatch": None}
    assert data["permissions"] == {"contents": "read"}
    assert data["concurrency"]["cancel-in-progress"] is False
    job = data["jobs"]["macos-107-native-gui-ipc"]
    assert job["runs-on"] == "macos-15"
    assert job["timeout-minutes"] == 65


def test_official_signed_native_installer_has_no_fallback_to_host_kicad() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "kicad-unified-universal-10.0.7.dmg" in source
    assert "kicad-downloads.s3.cern.ch" in source
    assert "mirrors.mit.edu" in source
    assert "codesign --verify --deep --strict" in source
    assert "Authority=.*KiCad" in source
    assert '"$cli" version' in source
    assert "'10.0.7'" in source
    assert "KICAD_MAC_CLI=$cli" in source
    assert "KICAD_MAC_PCB=$pcb" in source
    assert "KICAD_CONFIG_HOME=" in source
    for name in ("sym-lib-table", "fp-lib-table", "design-block-lib-table"):
        assert name in source


def test_gui_and_cli_both_mandatory_with_sanitized_evidence_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "KICAD_MCP_GUI_SMOKE_REQUIRED=1" in source
    assert "KICAD_GUI_SMOKE_PCB_ONLY=1" in source
    assert "tests/gui/test_kicad_gui_live_context.py" in source
    assert "scripts/kicad_canary.py run" in source
    assert 'out["testCount"]==2' in source
    assert 'out["failures"]==0' in source
    assert 'out["skips"]==0' in source
    assert 'out.get("nativeSteps")==32' in source
    assert 'out.get("differentialMatches")==5' in source
    assert 'out["verdict"]="pass" if success else "fail"' in source
    assert "if: always()" in source
    assert "summary.json" in source
    assert "artifacts/kicad-10-0-7-macos/summary.json" in source
    assert (
        "artifacts/kicad-10-0-7-macos/internal"
        not in source.split("name: Upload only bounded summary", maxsplit=1)[1].split(
            "name: Cleanup isolated macOS installation", maxsplit=1
        )[0]
    )
    assert "retention-days: 7" in source
