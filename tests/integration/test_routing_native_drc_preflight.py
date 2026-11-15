"""Opt-in real KiCad CLI/SWIG routing DRC acceptance on a disposable fixture."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.pcb.route_drc_preflight import run_route_drc_preflight
from kicad_mcp.routing.manual_tracks import TrackSpec

pytestmark = pytest.mark.skipif(
    os.environ.get("KICAD_MCP_RUN_ROUTING_NATIVE_PREFLIGHT") != "1",
    reason="Only run on an authorized KiCad host with native PCB Python and CLI",
)


def test_native_preflight_accepts_connected_route_but_rejects_new_shorts() -> None:
    root = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "benchmark_projects"
        / "fail_dirty_transfer_wrong_pad_nets"
    )
    pcb = root / "demo.kicad_pcb"
    project = root / "demo.kicad_pro"
    source = pcb.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    config = get_config()
    cli = config.kicad_cli
    if not cli.is_file() or not (cli.parent / "python.exe").is_file():
        pytest.skip("KiCad-bundled native Python/CLI not installed")

    good = run_route_drc_preflight(
        source.decode("utf-8"),
        [TrackSpec(10.95, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )
    bad = run_route_drc_preflight(
        source.decode("utf-8"),
        [TrackSpec(9.05, 10, 19.05, 10, "F_Cu", 0.25, "MID")],
        project_file=project,
        kicad_cli=cli,
    )

    assert good == {
        "accepted": True,
        "introducedViolations": 0,
        "unconnectedBefore": 1,
        "unconnectedAfter": 0,
    }
    assert bad["accepted"] is False
    assert bad["introducedViolations"] >= 1
    assert hashlib.sha256(pcb.read_bytes()).hexdigest() == digest
