from __future__ import annotations

from scripts import check_architecture_boundaries as boundaries
from tests.architecture_source_helpers import _function_span, _imports


def test_architecture_checker_tracks_document_settings_modules() -> None:
    assert "kicad_mcp.schematic.document_settings" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.document_settings" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_document_settings" in boundaries.DOMAIN_MODULES


def test_document_settings_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_document_settings.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[
        "kicad_mcp.tools.schematic_document_settings"
    ] == ("kicad_mcp.tools.schematic",)


def test_document_settings_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_document_settings.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_document_settings"] == 300
