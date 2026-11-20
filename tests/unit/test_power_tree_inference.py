"""A PCB footprint's X coordinate is not a power-distribution contract."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.config import get_config
from kicad_mcp.project import design_spec


@pytest.mark.parametrize(
    ("input_net", "output_net"),
    [("+3V3", "+5V"), ("+5V", "+5V")],
)
def test_inference_does_not_order_unrelated_connectors_into_power_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    input_net: str,
    output_net: str,
) -> None:
    board = tmp_path / "demo.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    monkeypatch.setattr(get_config(), "pcb_file", board)
    monkeypatch.setattr(
        "kicad_mcp.tools.board_file._parse_board_footprint_blocks",
        lambda _text: {
            "J1": {
                "name": "Connector_Generic:Conn_01x04",
                "value": "LOW_VOLTAGE",
                "x_mm": 4.0,
                "y_mm": 10.0,
                "net_names": [input_net, "GND", "SDA_LV", "SCL_LV"],
            },
            "J2": {
                "name": "Connector_Generic:Conn_01x04",
                "value": "HIGH_VOLTAGE",
                "x_mm": 57.0,
                "y_mm": 10.0,
                "net_names": [output_net, "GND", "SDA_HV", "SCL_HV"],
            },
        },
    )

    inferred, notes = design_spec._infer_design_intent_from_board()
    assert inferred.connector_refs == ["J1", "J2"]
    assert inferred.power_tree_refs == []
    assert any("power-tree" in note.lower() for note in notes)


def test_explicit_power_distribution_order_is_still_enforced() -> None:
    explicit = design_spec.ProjectDesignIntent(power_tree_refs=["J1", "U1", "U2"])
    inferred = design_spec.ProjectDesignIntent()
    resolved = design_spec._merge_design_intent(explicit, inferred)
    assert resolved.power_tree_refs == ["J1", "U1", "U2"]
