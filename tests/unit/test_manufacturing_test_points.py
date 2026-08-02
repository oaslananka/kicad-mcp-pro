"""Unit tests for test point management tools (FAZ 8.1).
Tools: pcb_list_test_points, pcb_add_test_point,
pcb_optimize_test_point_placement, pcb_check_test_coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.test_points import (
    _collect_board_nets,
    _load_test_points,
    _save_test_points,
)
from tests.conftest import call_tool_text


def test_test_points_empty(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._test_points_path", lambda: tmp_path / "tp.json"
    )
    state = _load_test_points()
    assert state["test_points"] == []


def test_save_and_load_test_point(tmp_path: Path, monkeypatch) -> None:
    tp_path = tmp_path / "tp.json"
    monkeypatch.setattr("kicad_mcp.tools.test_points._test_points_path", lambda: tp_path)
    state = {"test_points": [{"net_name": "GND", "x_mm": 10, "y_mm": 20, "diameter_mm": 1.0}]}
    _save_test_points(state)
    loaded = _load_test_points()
    assert len(loaded["test_points"]) == 1
    assert loaded["test_points"][0]["net_name"] == "GND"


@pytest.mark.anyio
async def test_list_test_points_empty(tmp_path: Path, monkeypatch) -> None:
    tp_path = tmp_path / "tp.json"
    monkeypatch.setattr("kicad_mcp.tools.test_points._test_points_path", lambda: tp_path)
    server = create_server()
    result = await call_tool_text(server, "pcb_list_test_points", {})
    payload = json.loads(result)
    assert payload["count"] == 0


def test_collect_board_nets_file_fallback(tmp_path: Path, monkeypatch) -> None:
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text(
        '(kicad_pcb (net 0 "") (net 1 "GND") (net 2 "+5V"))\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("kicad_mcp.tools.test_points._get_pcb_file", lambda: pcb_file)
    nets = _collect_board_nets()
    names = {n["name"] for n in nets}
    assert "GND" in names
    assert "+5V" in names


class _DeprecatedCodeNet:
    def __init__(self, name: str) -> None:
        self.name = name

    @property
    def code(self) -> int:  # pragma: no cover - should never be touched
        raise AssertionError("deprecated net code was accessed")


class _BoardWithDeprecatedNetCode:
    def get_nets(self):  # type: ignore[no-untyped-def]
        return [_DeprecatedCodeNet("GND")]


def test_collect_board_nets_uses_net_names_not_deprecated_codes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points.get_board", lambda: _BoardWithDeprecatedNetCode()
    )

    assert _collect_board_nets() == [{"code": None, "name": "GND"}]


@pytest.mark.anyio
async def test_optimize_test_points_reports_unavailable_via_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PartiallyReadableBoard:
        def get_nets(self) -> list[object]:
            return [type("Net", (), {"name": "GND"})()]

        def get_footprints(self) -> list[object]:
            return []

        def get_vias(self) -> list[object]:
            raise OSError("via IPC read failed")

    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": [{"net_name": "GND"}]},
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points.get_board",
        lambda: PartiallyReadableBoard(),
    )
    server = create_server()

    result = await call_tool_text(server, "pcb_optimize_test_point_placement", {})

    assert "Could not optimize via live board" in result
    assert "via IPC read failed" in result
