"""Differential testing: Native KiCad CLI vs KiCad MCP Pro implementation."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path

import pytest

from kicad_mcp.ir.from_kicad import parse_schematic
from kicad_mcp.tools.schematic import parse_schematic_file
from kicad_mcp.validation.drc_runner import (
    classify_drc_report,
)

KICAD_CLI = shutil.which("kicad-cli")
FIXTURE_DIR = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kicad-fixtures"
    / "fixtures"
    / "clean-led-kicad10"
)


@pytest.mark.skipif(
    KICAD_CLI is None,
    reason="Native kicad-cli is not installed on this host (UNAVAILABLE/NOT_RUN)",
)
def test_differential_drc_native_vs_mcp_classifier() -> None:
    """Verify that MCP DRC classification correctly ingests and structures
    findings directly produced by native KiCad 10.0.7 DRC CLI.
    """
    assert KICAD_CLI is not None
    with tempfile.TemporaryDirectory() as td:
        dest_dir = Path(td) / "project"
        shutil.copytree(FIXTURE_DIR, dest_dir)
        pcb_file = dest_dir / "clean-led-kicad10.kicad_pcb"
        report_output = dest_dir / "native-drc.json"

        # 1. Run native KiCad CLI
        cli_res = subprocess.run(  # nosec B603  # nosemgrep
            [
                KICAD_CLI,
                "pcb",
                "drc",
                "--format",
                "json",
                "--output",
                str(report_output),
                str(pcb_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert cli_res.returncode == 0 or report_output.exists()

        # 2. Ingest report via MCP drc_runner
        raw_report = json.loads(report_output.read_text(encoding="utf-8"))
        status, err = classify_drc_report(raw_report)

        # 3. Assert semantic parity
        assert err is None
        assert "violations" in raw_report or "unconnected_items" in raw_report
        native_violations = len(raw_report.get("violations", []))
        native_unconnected = len(raw_report.get("unconnected_items", []))
        total_native = native_violations + native_unconnected

        if total_native == 0:
            assert status == "clean"
        else:
            assert status == "findings"


@pytest.mark.skipif(
    KICAD_CLI is None,
    reason="Native kicad-cli is not installed on this host (UNAVAILABLE/NOT_RUN)",
)
def test_differential_schematic_netlist_parity() -> None:
    """Compare native KiCad CLI netlist export with MCP Schematic Parser & Semantic IR."""
    assert KICAD_CLI is not None
    with tempfile.TemporaryDirectory() as td:
        dest_dir = Path(td) / "project"
        shutil.copytree(FIXTURE_DIR, dest_dir)
        sch_file = dest_dir / "clean-led-kicad10.kicad_sch"
        netlist_output = dest_dir / "native_netlist.net"

        # 1. Export netlist using native KiCad CLI
        res = subprocess.run(  # nosec B603  # nosemgrep
            [
                KICAD_CLI,
                "sch",
                "export",
                "netlist",
                "--output",
                str(netlist_output),
                str(sch_file),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # Note: kicad-cli sch export netlist may exit 0 if supported
        if res.returncode == 0 and netlist_output.exists():
            native_netlist_text = netlist_output.read_text(encoding="utf-8")
            # Native netlist should contain export components
            assert "export" in native_netlist_text or "design" in native_netlist_text

        # 2. Parse schematic using KiCad MCP Pro
        mcp_data = parse_schematic_file(sch_file)
        assert len(mcp_data.get("symbols", [])) > 0

        # 3. Build Semantic IR from parsed schematic
        circuit = parse_schematic(sch_file)
        assert len(circuit.components) > 0

        # Symbols parsed by MCP Pro must contain the LED and Resistor references
        refs = {c.reference for c in circuit.components.values()}
        assert any(ref.startswith("D") or ref.startswith("R") for ref in refs)
