"""Bounded placement topology model for critical component review (#1582, T4).

Provides pure-domain representations of components, pins, nets, and board topology
for verifying decoupling, crystal, and SMPS placement against electrical intent.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PlacementPinTopology(BaseModel):
    """Pin-level electrical and geometric context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pin_number: str
    net_name: str
    pin_type: Literal[
        "power_input",
        "power_output",
        "ground",
        "oscillator",
        "switch_node",
        "signal",
        "passive",
        "unspecified",
    ] = "unspecified"
    location_mm: tuple[float, float] | None = None
    layer: str = "F.Cu"


class PlacementComponentTopology(BaseModel):
    """Component-level placement and connectivity context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reference: str
    component_type: Literal[
        "ic",
        "capacitor",
        "crystal",
        "smps",
        "inductor",
        "connector",
        "other",
    ] = "other"
    value: str = ""
    location_mm: tuple[float, float] | None = None
    layer: str = "F.Cu"
    rotation_deg: float = 0.0
    pins: list[PlacementPinTopology] = Field(default_factory=list)
    companion_refs: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def find_pin(self, pin_number: str) -> PlacementPinTopology | None:
        """Find pin by pin number."""
        for p in self.pins:
            if p.pin_number == pin_number:
                return p
        return None

    def power_pins(self) -> list[PlacementPinTopology]:
        """Return pins identified as power input or power rails."""
        return [
            p
            for p in self.pins
            if p.pin_type in ("power_input", "power_output")
            or (
                p.net_name
                and not p.net_name.upper().startswith(("GND", "VSS", "UNCONNECTED"))
                and any(
                    token in p.net_name.upper()
                    for token in ("VCC", "VDD", "3V3", "5V", "12V", "VBUS", "VIN", "VREF")
                )
            )
        ]

    def ground_pins(self) -> list[PlacementPinTopology]:
        """Return pins identified as ground returns."""
        return [
            p
            for p in self.pins
            if p.pin_type == "ground"
            or (p.net_name and any(g in p.net_name.upper() for g in ("GND", "VSS", "0V")))
        ]


class PlacementBoardTopology(BaseModel):
    """Board-level placement topology snapshot for engineering review."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    components: dict[str, PlacementComponentTopology] = Field(default_factory=dict)
    has_ground_plane: bool = False
    ground_plane_layers: list[str] = Field(default_factory=list)
    has_routing_evidence: bool = False
    unsupported_geometry: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
