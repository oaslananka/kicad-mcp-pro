from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "kicad-live-e2e.yml"
PACKAGE = ROOT / "package.json"


def test_kicad11_workflow_reports_read_write_and_export_artifacts_separately() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts/kicad11_headless_canary.py" in workflow
    for protected_path in (
        "src/kicad_mcp/adapter_matrix.py",
        "src/kicad_mcp/ipc/**",
        "src/kicad_mcp/server_info.py",
        "integrations/common/kicad-adapter-matrix.json",
    ):
        assert workflow.count(protected_path) == 2
    for surface in ("read", "write", "export"):
        assert f"kicad-11-headless-{surface}" in workflow
        assert f"artifacts/kicad-11-preview/{surface}" in workflow


def test_adapter_matrix_drift_check_is_part_of_metadata_gate() -> None:
    package = PACKAGE.read_text(encoding="utf-8")

    assert '"adapter-matrix:check"' in package
    assert "adapter-matrix:check" in package.split('"check:meta"', 1)[1]


def test_stable_kicad_workflow_pins_10_0_6_canary() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "kicad-10-0-6-canary:" in workflow
    assert "KiCad 10.0.6 canary" in workflow
    assert 'test "$(kicad-cli version)" = "10.0.6"' in workflow
    assert "artifacts/kicad-10-0-6" in workflow
    assert "kicad-10-0-5-canary:" not in workflow
