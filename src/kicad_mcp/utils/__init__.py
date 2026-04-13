"""Utility helpers for KiCad MCP Pro."""

from .freerouting import FreeRoutingResult, FreeRoutingRunner
from .layers import CANONICAL_LAYER_NAMES, resolve_layer, resolve_layer_name
from .sexpr import _escape_sexpr_string, _extract_block, _sexpr_string, _unescape_sexpr_string
from .units import _coord_nm, mil_to_mm, mm_to_mil, mm_to_nm, nm_to_mm

__all__ = [
    "CANONICAL_LAYER_NAMES",
    "FreeRoutingResult",
    "FreeRoutingRunner",
    "_coord_nm",
    "_escape_sexpr_string",
    "_extract_block",
    "_sexpr_string",
    "_unescape_sexpr_string",
    "mil_to_mm",
    "mm_to_mil",
    "mm_to_nm",
    "nm_to_mm",
    "resolve_layer",
    "resolve_layer_name",
]
