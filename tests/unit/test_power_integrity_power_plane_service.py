from __future__ import annotations

from dataclasses import dataclass, field

from kicad_mcp.models.power_integrity import PowerPlaneInput
from kicad_mcp.power_integrity.power_plane import PowerIntegrityPowerPlaneService


@dataclass
class FakeBackend:
    layer_value: int = 0
    supported: bool = True
    exists: bool = False
    bounds_value: tuple[float, float, float, float] | None = (0.0, 0.0, 100.0, 80.0)
    calls: list[tuple[object, ...]] = field(default_factory=list)

    def resolve_layer(self, layer: str) -> int:
        self.calls.append(("resolve", layer))
        return self.layer_value

    def is_supported_copper_layer(self, layer: int) -> bool:
        self.calls.append(("supported", layer))
        return self.supported

    def zone_exists(self, net_name: str, layer: int) -> bool:
        self.calls.append(("exists", net_name, layer))
        return self.exists

    def plane_bounds(self) -> tuple[float, float, float, float] | None:
        self.calls.append(("bounds",))
        return self.bounds_value

    def create_plane(
        self,
        *,
        net_name: str,
        layer: int,
        clearance_mm: float,
        bounds: tuple[float, float, float, float],
    ) -> None:
        self.calls.append(("create", net_name, layer, clearance_mm, bounds))


def _payload(layer: str = "F_Cu") -> PowerPlaneInput:
    return PowerPlaneInput(net_name="3V3", layer=layer, clearance_mm=0.5)


def test_service_rejects_unsupported_layer_before_board_queries() -> None:
    backend = FakeBackend(layer_value=7, supported=False)

    result = PowerIntegrityPowerPlaneService().generate(_payload("In1_Cu"), backend)

    assert result == "Power plane generation currently supports only F_Cu and B_Cu."
    assert backend.calls == [("resolve", "In1_Cu"), ("supported", 7)]


def test_service_preserves_existing_zone_and_missing_bounds_messages() -> None:
    existing = FakeBackend(layer_value=1, exists=True)
    assert PowerIntegrityPowerPlaneService().generate(_payload(), existing) == (
        "A copper zone for '3V3' already exists on F_Cu."
    )
    assert ("bounds",) not in existing.calls

    missing = FakeBackend(layer_value=1, bounds_value=None)
    assert PowerIntegrityPowerPlaneService().generate(_payload(), missing) == (
        "Could not determine board bounds. Add an Edge.Cuts outline or at least one "
        "footprint before generating a power plane."
    )
    assert not any(call[0] == "create" for call in missing.calls)


def test_service_delegates_creation_and_preserves_success_text() -> None:
    backend = FakeBackend(layer_value=1, bounds_value=(1.0, 2.0, 50.0, 40.0))

    result = PowerIntegrityPowerPlaneService().generate(_payload(), backend)

    assert result == "Generated a copper plane for '3V3' on F_Cu with 0.500 mm clearance."
    assert backend.calls[-1] == ("create", "3V3", 1, 0.5, (1.0, 2.0, 50.0, 40.0))
