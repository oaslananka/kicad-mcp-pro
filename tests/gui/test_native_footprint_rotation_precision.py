"""Opt-in native KiCad C++ versus registered MCP rotation parity regression."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.connection import get_board, reset_connection
from kicad_mcp.pcb.live_edit_runtime import reset_live_edit_service
from kicad_mcp.server import build_server
from kicad_mcp.tools import pcb
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import call_tool_text
from tests.gui.test_native_ipc_discovery_recovery import (
    FIXTURE,
    _configure_private_project,
    _installed_bin_dir,
    _private_editor,
)
from tests.integration.test_native_mounting_hole_keepout import _append_objects

OPT_IN = "KICAD_NATIVE_WINDOWS_ROTATION_BIN"
pytestmark = [
    pytest.mark.anyio,
    pytest.mark.gui,
    pytest.mark.slow,
    pytest.mark.skipif(
        sys.platform != "win32" or not os.environ.get(OPT_IN),
        reason=f"Set {OPT_IN} to an installed KiCad 10.0 bin directory on Windows",
    ),
]

_STOCK = (
    ("Package_DFN_QFN:QFN-28-1EP_5x5mm_P0.5mm_EP3.35x3.35mm", "U2", 35),
    ("Resistor_SMD:R_0603_1608Metric", "R1", 60),
    ("Button_Switch_SMD:SW_SPST_TL3342", "SW1", 80),
)

# This subprocess is an independent test oracle only. Production remains on IPC.
_NATIVE_ORACLE = """
import sys
from pathlib import Path
import pcbnew

path = Path(sys.argv[1])
board = pcbnew.LoadBoard(str(path))
footprints = list(board.GetFootprints())
assert len(footprints) == 3
initial = {f.GetReference(): (f.GetPosition().x, f.GetPosition().y)
           for f in footprints}
for cycle in range(2):
    for restored in (False, True):
        for footprint in footprints:
            x, y = initial[footprint.GetReference()]
            if not restored:
                x, y = x + 1234567, y + 2345678
            footprint.SetPosition(pcbnew.VECTOR2I(x, y))
            delta = -37.25 if restored else 37.25
            footprint.Rotate(footprint.GetPosition(), pcbnew.EDA_ANGLE(delta, pcbnew.DEGREES_T))
            assert (footprint.GetPosition().x, footprint.GetPosition().y) == (x, y)
            assert abs(footprint.GetOrientationDegrees() - (0 if restored else 37.25)) < 1e-8
        assert pcbnew.SaveBoard(str(path.with_name(f"native_{cycle}_{restored}.kicad_pcb")), board)
"""


def _mismatch_references(board: Path, report: Path) -> set[str]:
    code, stdout, stderr = _run_cli(
        "pcb",
        "drc",
        "--format",
        "json",
        "--severity-all",
        "--output",
        str(report),
        str(board),
    )
    assert code == 0, (stdout, stderr)
    violations = json.loads(report.read_text(encoding="utf-8"))["violations"]
    assert all(v["type"] == "lib_footprint_mismatch" for v in violations), violations
    refs = {v["items"][0]["description"].rsplit(maxsplit=1)[-1] for v in violations}
    assert len(refs) == len(violations)
    assert refs <= {ref for _, ref, _ in _STOCK}
    return refs


async def test_registered_rotation_matches_native_library_parity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bin_dir = _installed_bin_dir(os.environ[OPT_IN])
    root = bin_dir.parent / "share/kicad/footprints"
    libraries = [
        root / (library.split(":")[0] + ".pretty") / (library.split(":")[1] + ".kicad_mod")
        for library, _, _ in _STOCK
    ]
    original = {path: path.read_bytes() for path in libraries}
    fixture_bytes = FIXTURE.read_bytes()
    with TemporaryDirectory(prefix="kicad-rotation-parity-") as scratch:
        try:
            board, env, endpoint = _configure_private_project(Path(scratch), bin_dir, monkeypatch)
            for key in ("KICAD10_TEMPLATE_DIR", "KICAD10_SYMBOL_DIR", "KICAD10_FOOTPRINT_DIR"):
                monkeypatch.setenv(key, env[key])
            get_config().footprint_library_dir = root
            blocks = [
                pcb._render_board_footprint_block(
                    library,
                    reference=ref,
                    value=library.split(":")[1],
                    x_mm=x,
                    y_mm=30,
                    rotation=0,
                    pad_nets={},
                )
                for library, ref, x in _STOCK
            ]
            _append_objects(board, board.read_text(encoding="utf-8"), *blocks)
            assert not _mismatch_references(board, board.with_name("baseline.json"))
            oracle = Path(scratch) / "native_oracle.py"
            oracle.write_text(_NATIVE_ORACLE, encoding="utf-8")
            subprocess.run(
                [str(bin_dir / "python.exe"), "-I", str(oracle), str(board)],
                env=env,
                check=True,
                capture_output=True,
                timeout=30,
            )
            expected = {
                (cycle, restored): _mismatch_references(
                    board.with_name(f"native_{cycle}_{restored}.kicad_pcb"),
                    board.with_name(f"native_{cycle}_{restored}.json"),
                )
                for cycle in range(2)
                for restored in (False, True)
            }
            with _private_editor(bin_dir / "pcbnew.exe", board, env, endpoint):
                live = get_board()
                live.save()
                assert not _mismatch_references(board, board.with_name("live_baseline.json"))
                server = build_server("full")
                ids = {f.reference_field.text.value: f.id.value for f in live.get_footprints()}
                assert len(ids) == 3
                for cycle in range(2):
                    for restored in (False, True):
                        for _, ref, x in _STOCK:
                            result = await call_tool_text(
                                server,
                                "pcb_move_footprint",
                                {
                                    "reference": ref,
                                    "x_mm": float(x) if restored else x + 1.234567,
                                    "y_mm": 30.0 if restored else 32.345678,
                                    "rotation_deg": 0.0 if restored else 37.25,
                                },
                            )
                            assert "with verified rotation" in result, result
                        live.save()
                        actual = _mismatch_references(
                            board, board.with_name(f"mcp_{cycle}_{restored}.json")
                        )
                        assert actual == expected[(cycle, restored)]
                        assert {
                            f.reference_field.text.value: f.id.value for f in live.get_footprints()
                        } == ids
        finally:
            reset_live_edit_service()
            reset_connection()
            reset_config()
    assert FIXTURE.read_bytes() == fixture_bytes
    assert all(path.read_bytes() == content for path, content in original.items())
