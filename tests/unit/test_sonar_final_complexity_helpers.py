"""Regression checks for bounded schematic and PCB orchestration helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kicad_mcp.models.pcb import SyncPcbFromSchematicInput
from kicad_mcp.tools import pcb, schematic


def test_child_symbol_scanner_ignores_escaped_quoted_subexpressions() -> None:
    block = (
        '(symbol "Root" (property "Value" "literal \\"(symbol Fake)\\"") '
        '(symbol "Root_1_1" (pin a)))'
    )
    children = schematic._extract_child_symbol_blocks(block)
    assert len(children) == 1
    assert children[0][0] == "Root_1_1"


def test_schematic_power_classification_respects_flags_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(schematic, "_component_to_symbol_dict", lambda component: component)
    components = [
        {"lib_id": "custom:RES"},
        {"lib_id": "custom:VCC"},
        {"lib_id": "power:GND"},
    ]
    symbols, powers = schematic._api_components_by_power_flag(components, {"custom:VCC": True})
    assert [x["lib_id"] for x in symbols] == ["custom:RES"]
    assert [x["lib_id"] for x in powers] == ["custom:VCC", "power:GND"]


def test_merge_api_wires_retains_uuid_and_unmatched_compatibility() -> None:
    def point(x: int, y: int) -> SimpleNamespace:
        return SimpleNamespace(x=x, y=y)

    wire = SimpleNamespace(start=point(1, 2), end=point(3, 4))
    original = [
        {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0, "uuid": "same"},
        {"x1": 5.0, "y1": 6.0, "x2": 7.0, "y2": 8.0, "uuid": "extra"},
    ]
    result = schematic._merged_api_schematic_wires([wire], original)
    assert len(result) == 2
    assert result[0]["uuid"] == "same"
    assert result[1] == original[1]


def test_pcb_sync_net_data_respects_net_names_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        pcb, "_export_schematic_net_map", lambda: ({("U1", "1"): "GND"}, "exported")
    )
    monkeypatch.setattr(
        pcb,
        "_schematic_pad_net_summary",
        lambda components, net_map: {"size": len(components), "net_count": len(net_map)},
    )
    with_nets = pcb._pcb_sync_net_data([{"reference": "U1"}], SyncPcbFromSchematicInput())
    without_nets = pcb._pcb_sync_net_data(
        [{"reference": "U1"}], SyncPcbFromSchematicInput(use_net_names=False)
    )
    assert with_nets == ({("U1", "1"): "GND"}, "exported", {"size": 1, "net_count": 1})
    assert without_nets == ({}, "", {"size": 1, "net_count": 0})


def test_pcb_sync_write_and_reload_only_when_changes_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        pcb, "_transactional_board_write", lambda mutator: calls.append(mutator("board"))
    )
    monkeypatch.setattr(
        pcb, "_replace_board_blocks", lambda current, replacements, additions: current + "+sync"
    )
    monkeypatch.setattr(pcb, "_auto_place_force_directed_board_file", lambda **kwargs: "auto")
    monkeypatch.setattr(pcb, "_reload_board_after_file_sync", lambda: "reloaded")
    payload = SyncPcbFromSchematicInput(allow_open_board=True)
    assert pcb._apply_pcb_sync_changes(payload, [], {}) == ("", "")
    assert calls == []
    assert pcb._apply_pcb_sync_changes(payload, ["add"], {}) == ("auto", "reloaded")
    assert calls == ["board+sync"]
