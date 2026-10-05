from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.test_signal_integrity_architecture_helpers import (
    adapter_boundary_state,
    root_register_contract,
    tracked_module_state,
)

SERVICE = "kicad_mcp.signal_integrity.via_stub"
ADAPTER = "kicad_mcp.tools.signal_integrity_via_stub"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_via_stub_service_and_adapter() -> None:
    assert tracked_module_state(SERVICE, ADAPTER, ROOT) == (True, True, True, True)


def test_via_stub_adapter_stays_thin_and_away_from_root() -> None:
    imports, forbidden_prefixes, span, configured_limit = adapter_boundary_state(ADAPTER)

    assert ROOT not in imports
    assert forbidden_prefixes == (ROOT,)
    assert span is not None
    assert span <= 45
    assert configured_limit == 45


def test_si_root_delegates_via_stub_and_has_no_nested_tools() -> None:
    source, nested, span = root_register_contract(ROOT)

    assert nested == []
    for forbidden in (
        "si_check_via_stub",
        "ViaStubInput",
        "ViaType",
        "board_vias",
        "via_stub_resonance_ghz",
    ):
        assert forbidden not in source
    assert "signal_integrity_via_stub.register(mcp)" in source
    assert span is not None
    assert span <= 60
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 60
