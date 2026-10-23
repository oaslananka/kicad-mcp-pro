from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kicad_mcp.connection import KiCadConnectionError
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text, tool_text

REPO_ROOT = Path(__file__).resolve().parents[2]
EMPTY_PROJECT_FIXTURE = (
    REPO_ROOT / "packages" / "kicad-fixtures" / "fixtures" / "empty-project-kicad10"
)

EMPTY_PROJECT_TOOL_CASES: tuple[tuple[str, dict[str, object], str | None], ...] = (
    ("pcb_get_board_summary", {}, "Board summary"),
    ("pcb_get_footprints", {}, "No footprints"),
    ("pcb_get_nets", {}, "No nets"),
    ("pcb_get_layers", {}, "Enabled layers"),
    ("pcb_get_vias", {}, "No vias"),
    ("pcb_get_ratsnest", {}, "no nets to analyze"),
    ("pcb_get_selection", {}, "No PCB items are selected"),
    ("pcb_get_board_as_string", {}, "(kicad_pcb"),
    ("pcb_get_stackup", {}, "No stackup data"),
    ("pcb_get_design_rules", {}, "No .kicad_dru"),
    ("pcb_block_list", {}, '"blocks"'),
    ("pcb_get_footprint_layers", {"reference": "U1"}, '"found": false'),
    ("sch_get_symbols", {}, "no symbols"),
    ("sch_get_wires", {}, "no wires"),
    ("sch_get_labels", {}, "no labels"),
    ("sch_get_net_names", {}, "No named nets"),
    ("sch_check_power_flags", {}, "No obvious missing power flags"),
    ("sch_list_sheets", {}, "no child sheets"),
    ("sch_get_connectivity_graph", {}, "no connectivity"),
    ("sch_get_bounding_boxes", {}, "no symbols"),
    ("run_drc", {}, "DRC summary"),
    ("run_erc", {}, "ERC summary"),
    ("validate_design", {}, "Design validation summary"),
    ("project_quality_gate", {}, "Project quality gate"),
    ("schematic_quality_gate", {}, "Schematic quality gate"),
    ("pcb_quality_gate", {}, "PCB quality gate"),
)

DIAGNOSTIC_MARKERS = (
    "Diagnostics:",
    '"diagnostics"',
    "- Source:",
    "summary:",
    "quality gate:",
)


@pytest.fixture
def empty_project(tmp_path: Path) -> Path:
    """Copy the shared empty project fixture so tools can write output state."""
    target = tmp_path / "empty-project-kicad10"
    shutil.copytree(EMPTY_PROJECT_FIXTURE, target)
    return target


@pytest.fixture
def empty_project_server(
    empty_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_cli: Path,
) -> object:
    """Build a deterministic server for empty-project tool regression checks."""
    _ = fake_cli

    def no_live_board() -> object:
        raise KiCadConnectionError("No live board for empty-project regression.")

    def fake_cli_report(variants: list[list[str]]) -> tuple[int, str, str]:
        command = variants[0]
        report_path = Path(command[command.index("--output") + 1])
        payload: dict[str, object]
        if "drc" in command:
            payload = {
                "violations": [],
                "unconnected_items": [],
                "items_not_passing_courtyard": [],
            }
        else:
            payload = {"violations": [], "sheets": []}
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload), encoding="utf-8")
        return 0, "", ""

    monkeypatch.setattr("kicad_mcp.tools.pcb.get_board", no_live_board)
    monkeypatch.setattr("kicad_mcp.tools.validation._run_cli_variants", fake_cli_report)

    server = build_server("full")
    return server


def test_empty_project_fixture_contains_board_and_schematic() -> None:
    assert (EMPTY_PROJECT_FIXTURE / "empty-project-kicad10.kicad_pro").is_file()
    assert (EMPTY_PROJECT_FIXTURE / "empty-project-kicad10.kicad_pcb").is_file()
    assert (EMPTY_PROJECT_FIXTURE / "empty-project-kicad10.kicad_sch").is_file()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_text"),
    EMPTY_PROJECT_TOOL_CASES,
)
async def test_empty_project_read_tools_return_diagnostic_non_errors(
    empty_project: Path,
    empty_project_server,
    tool_name: str,
    arguments: dict[str, object],
    expected_text: str | None,
) -> None:
    await call_tool_text(
        empty_project_server,
        "kicad_set_project",
        {"project_dir": str(empty_project)},
    )

    result = await empty_project_server.call_tool(tool_name, arguments)
    text = tool_text(result)

    assert getattr(result, "isError", False) is False, text
    assert "TOOL_EXECUTION_FAILED" not in text
    assert "Traceback" not in text
    assert text.strip()
    if expected_text is not None:
        assert expected_text.casefold() in text.casefold()
    assert any(marker.casefold() in text.casefold() for marker in DIAGNOSTIC_MARKERS), text
