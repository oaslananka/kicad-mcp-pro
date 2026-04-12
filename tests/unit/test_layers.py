from __future__ import annotations

from kicad_mcp.utils.layers import resolve_layer_name


def test_layer_alias_resolution() -> None:
    assert resolve_layer_name("F.Cu") == "F_Cu"
