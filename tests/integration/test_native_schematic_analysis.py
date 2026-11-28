"""Opt-in native ERC/DRC and release-gate parity for #1953."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools import schematic, validation
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import call_tool_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/benchmark_projects/pass_minimal_mcu_board"


@pytest.mark.anyio
async def test_checked_analysis_preserves_native_quality_and_release_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_cli = os.environ.get("KICAD_NATIVE_ANALYSIS_CLI")
    if not configured_cli:
        pytest.skip("Explicit native KiCad analysis executable required")
    cli = Path(configured_cli).resolve(strict=True)
    assert cli.is_file()
    project = tmp_path / "project"
    project.mkdir()
    sources = tuple(sorted(FIXTURE.glob("*.kicad_*")))
    assert len(sources) == 3
    original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for source in sources:
        shutil.copy2(source, project / source.name)
    for key, value in {
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "KICAD_DOCUMENTS_HOME": str(tmp_path / "documents"),
        "KICAD_MCP_KICAD_CLI": str(cli),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_OUTPUT_DIR": str(project / "output"),
        "KICAD_MCP_OPERATING_MODE": "manufacturing",
        "KICAD_MCP_PROFILE": "manufacturing",
        "KICAD_MCP_HEADLESS": "true",
        "KICAD_MCP_KICAD_SOCKET_PATH": str(tmp_path / "unbound.sock"),
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    code, version, error = _run_cli("version")
    assert code == 0, error
    assert version.strip().startswith("10."), version

    def legacy_pair(path: Path) -> tuple[dict, list[dict]]:
        return schematic.parse_schematic_file(path), schematic.build_connectivity_groups(path)

    reports = tuple(
        project / "output" / name
        for name in ("schematic_quality_gate.json", "pcb_quality_gate.json")
    )

    def evaluate() -> list[validation.GateOutcome]:
        outcomes = [
            validation._evaluate_schematic_gate(),
            validation._evaluate_schematic_connectivity_gate(),
            validation._evaluate_pcb_gate(),
        ]
        for report in reports:
            assert json.loads(report.read_text(encoding="utf-8"))
        return outcomes

    with monkeypatch.context() as legacy:
        legacy.setattr(schematic, "analyze_schematic_file", legacy_pair)
        before = evaluate()
    for report in reports:
        report.unlink()
    after = evaluate()
    assert after == before
    assert all(outcome.status in {"PASS", "FAIL"} for outcome in after)
    assert any(outcome.status == "FAIL" for outcome in after)
    assert after[0].status == "FAIL"
    server = build_server("manufacturing")
    result = await call_tool_text(server, "export_manufacturing_package", {})
    assert "hard-blocked" in result
    assert "Gerber export completed" not in result
    assert "Drill export completed" not in result
    assert not (project / "output" / "gerber").exists()
    assert {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources} == original
    assert {
        p.name: hashlib.sha256((project / p.name).read_bytes()).hexdigest() for p in sources
    } == original
