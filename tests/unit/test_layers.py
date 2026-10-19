from __future__ import annotations

from pathlib import Path

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.tools.pcb import _board_file_layers, _file_backed_layers
from kicad_mcp.utils.layers import resolve_layer, resolve_layer_name


def test_layer_alias_resolution() -> None:
    assert resolve_layer_name("F.Cu") == "F_Cu"
    assert resolve_layer_name("In30.Cu") == "In30_Cu"


def test_resolve_layer_returns_board_layer_value() -> None:
    layer = resolve_layer("F.Cu")
    inner = resolve_layer("In30.Cu")

    assert isinstance(layer, int)
    assert layer == BoardLayer.BL_F_Cu
    assert inner == BoardLayer.Value("BL_In30_Cu")


def test_resolve_layer_rejects_unknown_layer() -> None:
    try:
        resolve_layer("Not.A.Layer")
    except ValueError as exc:
        assert "Unknown layer" in str(exc)
    else:
        raise AssertionError("resolve_layer() should reject invalid layers")


def test_board_file_layers_default_fallback() -> None:
    minimal_pcb = '(kicad_pcb (version 20260206) (generator_version "10.0"))'
    layers = _board_file_layers(minimal_pcb)

    assert len(layers) > 0
    assert any(layer["name"] == "F.Cu" for layer in layers)
    assert any(layer["name"] == "B.Cu" for layer in layers)
    assert any(layer["name"] == "Edge.Cuts" for layer in layers)


def test_board_file_layers_infers_from_segments_vias_and_zones() -> None:
    content = """
    (kicad_pcb (version 20260206)
      (segment (start 0 0) (end 2 2) (layer "F.Cu") (net 1))
      (via (at 2 2) (layers "F.Cu" "B.Cu") (net 1))
      (zone (net 1) (layers "F.Mask" "B.Mask"))
    )
    """

    layers = _board_file_layers(content)

    assert {str(item["name"]) for item in layers} == {"F.Cu", "B.Cu", "F.Mask", "B.Mask"}
    assert all(item["type"] == "inferred" for item in layers)


def test_board_file_layers_infers_from_footprint_and_nested_pad_layers() -> None:
    content = """
    (kicad_pcb (version 20260206)
      (footprint "Resistor_SMD:R_0805"
        (layer "B.Cu")
        (at 10 20)
        (property "Reference" "R1" (at 0 -1) (layer "B.SilkS"))
        (fp_line (start 0 0) (end 1 0) (layer "B.Fab"))
        (pad "1" smd rect (at 0 0) (size 1 1) (layers "B.Cu" "B.Mask"))
      )
    )
    """

    layers = _board_file_layers(content)

    assert {item["name"] for item in layers} == {"B.Cu", "B.SilkS", "B.Fab", "B.Mask"}
    assert all(item["type"] == "inferred" for item in layers)


def test_board_file_layers_explicit_table_precedes_inference() -> None:
    content = """
    (kicad_pcb (version 20260206)
      (layers
        (0 "F.Cu" signal)
        (31 "B.Cu" signal))
      (segment (start 0 0) (end 2 2) (layer "In1.Cu") (net 1))
    )
    """

    assert _board_file_layers(content) == [
        {"index": 0, "name": "F.Cu", "type": "signal"},
        {"index": 31, "name": "B.Cu", "type": "signal"},
    ]


def test_file_backed_layers_uses_kicad_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    minimal_pcb = "(kicad_pcb (version 20260206))"
    dummy_diagnostics = [
        "Diagnostics:",
        "- Source: file-backed",
        "- Fallback status: using file-backed .kicad_pcb parser",
    ]
    monkeypatch.setattr(
        "kicad_mcp.tools.pcb._load_file_backed_board",
        lambda exc: (Path("dummy.kicad_pcb"), minimal_pcb, dummy_diagnostics),
    )
    from kicad_mcp.connection import KiCadConnectionError

    result = _file_backed_layers(KiCadConnectionError("test"))

    assert "using KiCad defaults" in result
    assert "F.Cu" in result
    assert "B.Cu" in result
