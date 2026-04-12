"""Layer mapping helpers across KiCad versions."""

from __future__ import annotations

from typing import Final

from kipy.proto.board.board_types_pb2 import BoardLayer

CANONICAL_LAYER_NAMES: Final[tuple[str, ...]] = (
    "F_Cu",
    "B_Cu",
    "In1_Cu",
    "In2_Cu",
    "In3_Cu",
    "In4_Cu",
    "In5_Cu",
    "In6_Cu",
    "In7_Cu",
    "In8_Cu",
    "F_SilkS",
    "B_SilkS",
    "F_Mask",
    "B_Mask",
    "F_Fab",
    "B_Fab",
    "F_CrtYd",
    "B_CrtYd",
    "Edge_Cuts",
    "Dwgs_User",
    "Cmts_User",
    "Eco1_User",
    "Eco2_User",
)

_LAYER_ATTRS: Final[dict[str, str]] = {
    "F_Cu": "BL_F_Cu",
    "B_Cu": "BL_B_Cu",
    "In1_Cu": "BL_In1_Cu",
    "In2_Cu": "BL_In2_Cu",
    "In3_Cu": "BL_In3_Cu",
    "In4_Cu": "BL_In4_Cu",
    "In5_Cu": "BL_In5_Cu",
    "In6_Cu": "BL_In6_Cu",
    "In7_Cu": "BL_In7_Cu",
    "In8_Cu": "BL_In8_Cu",
    "F_SilkS": "BL_F_SilkS",
    "B_SilkS": "BL_B_SilkS",
    "F_Mask": "BL_F_Mask",
    "B_Mask": "BL_B_Mask",
    "F_Fab": "BL_F_Fab",
    "B_Fab": "BL_B_Fab",
    "F_CrtYd": "BL_F_CrtYd",
    "B_CrtYd": "BL_B_CrtYd",
    "Edge_Cuts": "BL_Edge_Cuts",
    "Dwgs_User": "BL_Dwgs_User",
    "Cmts_User": "BL_Cmts_User",
    "Eco1_User": "BL_Eco1_User",
    "Eco2_User": "BL_Eco2_User",
}

_ALIASES: Final[dict[str, str]] = {
    "F.Cu": "F_Cu",
    "B.Cu": "B_Cu",
    "Edge.Cuts": "Edge_Cuts",
    "F.SilkS": "F_SilkS",
    "B.SilkS": "B_SilkS",
    "F.Mask": "F_Mask",
    "B.Mask": "B_Mask",
    "F.Fab": "F_Fab",
    "B.Fab": "B_Fab",
    "F.CrtYd": "F_CrtYd",
    "B.CrtYd": "B_CrtYd",
    "Dwgs.User": "Dwgs_User",
    "Cmts.User": "Cmts_User",
    "Eco1.User": "Eco1_User",
    "Eco2.User": "Eco2_User",
}


def resolve_layer_name(layer_name: str) -> str:
    """Resolve user-supplied layer names to canonical KiCad names."""
    normalized = _ALIASES.get(layer_name, layer_name)
    if normalized not in _LAYER_ATTRS:
        choices = ", ".join(CANONICAL_LAYER_NAMES)
        raise ValueError(f"Unknown layer '{layer_name}'. Expected one of: {choices}")
    return normalized


def resolve_layer(layer_name: str) -> int:
    """Resolve a canonical layer name to a KiCad board layer enum value."""
    canonical = resolve_layer_name(layer_name)
    return int(getattr(BoardLayer, _LAYER_ATTRS[canonical]))
