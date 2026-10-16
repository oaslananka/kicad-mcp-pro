"""Unit tests for test point management tools (FAZ 8.1).
Tools: pcb_list_test_points, pcb_add_test_point,
pcb_optimize_test_point_placement, pcb_check_test_coverage.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_mcp.server import create_server
from kicad_mcp.tools.test_points import (
    _collect_board_nets,
    _load_test_points,
    _save_test_points,
    _sidecar_dir,
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


def test_sidecar_dir_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MagicMock()
    cfg.project_dir = None
    monkeypatch.setattr("kicad_mcp.tools.test_points.get_config", lambda: cfg)
    with pytest.raises(ValueError, match="No active project directory is configured"):
        _sidecar_dir()


def test_load_test_points_corrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tp_path = tmp_path / "corrupt.json"
    tp_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.tools.test_points._test_points_path", lambda: tp_path)
    state = _load_test_points()
    assert state == {"test_points": []}


def test_collect_board_nets_file_fallback_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kicad_mcp.tools.test_points.get_board", MagicMock(side_effect=OSError))
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._get_pcb_file",
        MagicMock(side_effect=OSError("pcb missing")),
    )
    assert _collect_board_nets() == []


@pytest.mark.anyio
async def test_pcb_add_test_point_unknown_net(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._collect_board_nets",
        lambda: [{"code": 1, "name": "GND"}],
    )
    server = create_server()
    result = await call_tool_text(
        server,
        "pcb_add_test_point",
        {"net_name": "NONEXISTENT", "x_mm": 10.0, "y_mm": 20.0},
    )
    assert "Net 'NONEXISTENT' not found in board" in result
    assert "Known nets: GND" in result


@pytest.mark.anyio
async def test_pcb_add_test_point_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tp_path = tmp_path / "test_points.json"
    monkeypatch.setattr("kicad_mcp.tools.test_points._test_points_path", lambda: tp_path)
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._collect_board_nets",
        lambda: [{"code": 1, "name": "SIG1"}],
    )
    server = create_server()
    result = await call_tool_text(
        server,
        "pcb_add_test_point",
        {"net_name": "SIG1", "x_mm": 15.5, "y_mm": 25.5, "diameter_mm": 1.2},
    )
    assert "Test point added for net 'SIG1' at (15.5, 25.5) mm with Ø1.2 mm" in result
    assert tp_path.exists()
    content = json.loads(tp_path.read_text(encoding="utf-8"))
    assert len(content["test_points"]) == 1
    assert content["test_points"][0]["net_name"] == "SIG1"


@pytest.mark.anyio
async def test_pcb_optimize_test_point_placement_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": []},
    )
    server = create_server()
    result = await call_tool_text(server, "pcb_optimize_test_point_placement", {})
    assert "No test points registered yet" in result


@pytest.mark.anyio
async def test_pcb_optimize_test_point_placement_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DummyNet:
        def __init__(self, name: str) -> None:
            self.name = name

    class DummyPos:
        def __init__(self, x: int, y: int) -> None:
            self.x = x
            self.y = y

    class DummyPad:
        def __init__(self, net_name: str, x: int, y: int) -> None:
            self.net = DummyNet(net_name)
            self.position = DummyPos(x, y)
            self.number = "1"

    class DummyFootprint:
        def __init__(self, pads: list[DummyPad]) -> None:
            self._pads = pads
            self.reference = "U1"

        def get_pads(self) -> list[DummyPad]:
            return self._pads

    class DummyVia:
        def __init__(self, net_name: str, x: int, y: int, drill: int) -> None:
            self.net = DummyNet(net_name)
            self.position = DummyPos(x, y)
            self.drill = drill

    class DummyBoard:
        def get_nets(self) -> list[DummyNet]:
            return [DummyNet("SIG1")]

        def get_footprints(self) -> list[DummyFootprint]:
            return [DummyFootprint([DummyPad("SIG1", 10_000_000, 20_000_000)])]

        def get_vias(self) -> list[DummyVia]:
            return [DummyVia("SIG1", 15_000_000, 25_000_000, 300_000)]

    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": [{"net_name": "SIG1"}]},
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points.get_board",
        lambda: DummyBoard(),
    )
    server = create_server()
    result = await call_tool_text(server, "pcb_optimize_test_point_placement", {})
    payload = json.loads(result)
    assert len(payload["suggestions"]) == 1
    candidates = payload["suggestions"][0]["candidates"]
    assert len(candidates) == 2
    types = {c["type"] for c in candidates}
    assert types == {"pad", "via"}


@pytest.mark.anyio
async def test_pcb_check_test_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    board_nets = [
        {"name": "GND"},
        {"name": "+3V3"},
        {"name": "SIG_A"},
        {"name": "SIG_B"},
    ]
    monkeypatch.setattr("kicad_mcp.tools.test_points._collect_board_nets", lambda: board_nets)

    # 1. Zero coverage of required nets (SIG_A, SIG_B)
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": []},
    )
    server = create_server()
    res1 = await call_tool_text(server, "pcb_check_test_coverage", {})
    data1 = json.loads(res1)
    assert data1["required_nets"] == 2
    assert data1["covered_nets"] == 0
    assert data1["coverage_pct"] == 0.0
    assert "SIG_A" in data1["uncovered_nets"]

    # 2. 50% coverage
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": [{"net_name": "SIG_A"}]},
    )
    res2 = await call_tool_text(server, "pcb_check_test_coverage", {})
    data2 = json.loads(res2)
    assert data2["covered_nets"] == 1
    assert data2["coverage_pct"] == 50.0

    # 3. 100% coverage
    monkeypatch.setattr(
        "kicad_mcp.tools.test_points._load_test_points",
        lambda: {"test_points": [{"net_name": "SIG_A"}, {"net_name": "SIG_B"}]},
    )
    res3 = await call_tool_text(server, "pcb_check_test_coverage", {})
    data3 = json.loads(res3)
    assert data3["covered_nets"] == 2
    assert data3["coverage_pct"] == 100.0
    assert data3["uncovered_nets"] == []
