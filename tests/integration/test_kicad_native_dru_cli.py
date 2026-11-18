"""Native KiCad regression for custom DRC rules (issue #1770).

Opt-in only: normal cross-platform suites must not require a system KiCad CLI.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import call_tool_text

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "kicad-fixtures"
    / "fixtures"
    / "clean-led-kicad10"
)


def _run_native_drc(project: Path, label: str) -> list[dict[str, object]]:
    board = project / "clean-led-kicad10.kicad_pcb"
    output = project / f"{label}-drc.json"
    return_code, stdout, stderr = _run_cli(
        "pcb", "drc", "--format", "json", "--output", str(output), str(board), timeout=90
    )
    assert return_code in {0, 5}, f"Native KiCad DRC failed: {return_code}\n{stdout}\n{stderr}"
    report = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(report.get("violations"), list), report
    return report["violations"]


@pytest.mark.anyio
async def test_generated_rule_changes_actual_native_kicad_drc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.environ.get("KICAD_DRC_NATIVE_ACCEPTANCE") != "1":
        pytest.skip("Explicit native KiCad 10 CI acceptance only")
    executable = shutil.which("kicad-cli")
    assert executable, "Native acceptance was enabled without KiCad CLI"
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", executable)
    reset_config()
    for suffix in (".kicad_pcb", ".kicad_pro", ".kicad_sch"):
        source = FIXTURE / f"clean-led-kicad10{suffix}"
        shutil.copy2(source, tmp_path / source.name)
    baseline = _run_native_drc(tmp_path, "before")

    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    reset_config()
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(tmp_path)})
    result = await call_tool_text(
        server,
        "drc_rule_create",
        {
            "name": "Native minimum track width",
            "constraint_type": "track_width",
            "min_value": 5.0,
            "condition": "A.Type == 'track'",
        },
    )
    assert "written" in result, result
    custom_file = tmp_path / "clean-led-kicad10.kicad_dru"
    text = custom_file.read_text(encoding="utf-8")
    assert text.startswith("(version 1)\n")
    assert "(min 5.0mm)" in text
    assert "(rules" not in text

    violations = _run_native_drc(tmp_path, "with-custom")

    def widths(items: list[dict[str, object]]) -> int:
        return sum(1 for item in items if "width" in str(item.get("type", "")).lower())

    assert widths(violations) > widths(baseline), (
        "KiCad DRC did not enforce the generated 5 mm track-width rule. "
        f"before={baseline!r}; after={violations!r}"
    )
