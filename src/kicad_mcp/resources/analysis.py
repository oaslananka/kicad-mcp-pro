"""Structured MCP resources for analysis assumptions and stackup context."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.mcpserver import MCPServer as FastMCP
from pydantic import BaseModel

from ..models.pcb import ImpedanceForTraceInput, SetStackupInput
from ..models.signal_integrity import (
    DecouplingPlacementInput,
    DifferentialPairSkewInput,
    LengthMatchingInput,
    StackupInput,
    TraceImpedanceInput,
    TraceWidthForImpedanceInput,
    ViaStubInput,
)
from ..tools.pcb import (
    _current_stackup_specs,
    _is_copper_stackup_layer,
    _total_stackup_thickness_mm,
)
from ..utils.impedance import (
    copper_thickness_mm,
    list_dielectric_materials,
    recommended_decoupling_distance_mm,
)


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)


def _blocked_json(resource: str, exc: Exception) -> str:
    return _json({"resource": resource, "status": "blocked", "error": str(exc)})


def _model_contract(model: type[BaseModel]) -> dict[str, object]:
    required: list[str] = []
    defaults: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if field.is_required():
            required.append(name)
        else:
            defaults[name] = field.get_default(call_default_factory=True)
    return {"required": required, "defaults": defaults}


def _materials_json() -> str:
    return _json(
        {
            "schema_version": "1.0",
            "schema": {
                "key": "stable material identifier used by SI tools",
                "name": "display material name",
                "er": "nominal relative permittivity",
                "loss_tangent": "nominal dielectric loss tangent",
                "description": "intended frequency and manufacturing context",
            },
            "materials": list_dielectric_materials(),
        }
    )


def _defaults_json() -> str:
    models: dict[str, type[BaseModel]] = {
        "trace_impedance": TraceImpedanceInput,
        "trace_width_for_impedance": TraceWidthForImpedanceInput,
        "differential_pair_skew": DifferentialPairSkewInput,
        "length_matching": LengthMatchingInput,
        "stackup_recommendation": StackupInput,
        "set_stackup": SetStackupInput,
        "impedance_for_existing_stackup": ImpedanceForTraceInput,
        "via_stub": ViaStubInput,
        "decoupling_placement": DecouplingPlacementInput,
    }
    return _json(
        {
            "schema_version": "1.0",
            "defaults": {name: _model_contract(model) for name, model in models.items()},
            "schemas": {name: model.model_json_schema() for name, model in models.items()},
            "derived_assumptions": {
                "one_ounce_copper_thickness_mm": round(copper_thickness_mm(1.0), 6),
                "decoupling_distance_examples_mm": {
                    "50_mhz": recommended_decoupling_distance_mm(50.0),
                    "250_mhz": recommended_decoupling_distance_mm(250.0),
                    "2000_mhz": recommended_decoupling_distance_mm(2000.0),
                },
            },
        }
    )


def _stackup_json() -> str:
    layers = _current_stackup_specs()
    return _json(
        {
            "schema_version": "1.0",
            "source": "active_board_project_state_or_pcb_file",
            "total_thickness_mm": _total_stackup_thickness_mm(layers),
            "copper_layer_count": sum(1 for layer in layers if _is_copper_stackup_layer(layer)),
            "layers": [
                {
                    **layer.model_dump(exclude_none=True),
                    "is_copper": _is_copper_stackup_layer(layer),
                }
                for layer in layers
            ],
        }
    )


def register(mcp: FastMCP) -> None:
    """Register structured analysis resources."""

    @mcp.resource("kicad://analysis/materials")
    def analysis_materials_resource() -> str:
        """JSON dielectric material library used by SI and EMC analysis."""
        try:
            return _materials_json()
        except Exception as exc:
            return _blocked_json("kicad://analysis/materials", exc)

    @mcp.resource("kicad://analysis/defaults")
    def analysis_defaults_resource() -> str:
        """JSON defaults and schemas for built-in analysis assumptions."""
        try:
            return _defaults_json()
        except Exception as exc:
            return _blocked_json("kicad://analysis/defaults", exc)

    @mcp.resource("kicad://analysis/stackup")
    def analysis_stackup_resource() -> str:
        """JSON stackup context consumed by SI, PI, and EMC workflows."""
        try:
            return _stackup_json()
        except Exception as exc:
            return _blocked_json("kicad://analysis/stackup", exc)
