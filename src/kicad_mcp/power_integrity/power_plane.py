"""FastMCP-independent power-plane generation orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..models.power_integrity import PowerPlaneInput


class PowerPlaneBackend(Protocol):
    """Backend operations required to generate a power plane."""

    def resolve_layer(self, layer: str) -> int: ...

    def is_supported_copper_layer(self, layer: int) -> bool: ...

    def zone_exists(self, net_name: str, layer: int) -> bool: ...

    def plane_bounds(self) -> tuple[float, float, float, float] | None: ...

    def create_plane(
        self,
        *,
        net_name: str,
        layer: int,
        clearance_mm: float,
        bounds: tuple[float, float, float, float],
    ) -> None: ...


@dataclass(frozen=True)
class PowerIntegrityPowerPlaneService:
    """Own power-plane generation decisions independently of FastMCP/KiCad bindings."""

    def generate(self, payload: PowerPlaneInput, backend: PowerPlaneBackend) -> str:
        layer_value = backend.resolve_layer(payload.layer)
        if not backend.is_supported_copper_layer(layer_value):
            return "Power plane generation currently supports only F_Cu and B_Cu."
        if backend.zone_exists(payload.net_name, layer_value):
            return f"A copper zone for '{payload.net_name}' already exists on {payload.layer}."

        bounds = backend.plane_bounds()
        if bounds is None:
            return (
                "Could not determine board bounds. Add an Edge.Cuts outline or at least one "
                "footprint before generating a power plane."
            )

        backend.create_plane(
            net_name=payload.net_name,
            layer=layer_value,
            clearance_mm=payload.clearance_mm,
            bounds=bounds,
        )
        return (
            f"Generated a copper plane for '{payload.net_name}' on {payload.layer} "
            f"with {payload.clearance_mm:.3f} mm clearance."
        )
