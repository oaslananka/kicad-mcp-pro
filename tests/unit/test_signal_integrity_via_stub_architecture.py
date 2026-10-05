from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.test_signal_integrity_architecture_helpers import (
    assert_adapter_boundary,
    assert_service_adapter_tracked,
    root_register_contract,
)

SERVICE = "kicad_mcp.signal_integrity.via_stub"
ADAPTER = "kicad_mcp.tools.signal_integrity_via_stub"
ROOT = "kicad_mcp.tools.signal_integrity"


def test_architecture_checker_tracks_via_stub_service_and_adapter() -> None:
    assert_service_adapter_tracked(SERVICE, ADAPTER, ROOT)


def test_via_stub_adapter_stays_thin_and_away_from_root() -> None:
    assert_adapter_boundary(ADAPTER, ROOT, line_limit=45)


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
    assert span <= 60
    assert boundaries.REGISTER_LINE_LIMITS[ROOT] <= 60
