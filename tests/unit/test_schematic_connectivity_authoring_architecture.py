from __future__ import annotations

import ast
from pathlib import Path

from scripts import check_architecture_boundaries as boundaries


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
    return imports


def _function_span(path: Path, name: str) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    node = matches[0]
    assert node.end_lineno is not None
    return node.end_lineno - node.lineno + 1


def test_architecture_checker_tracks_connectivity_authoring_modules() -> None:
    assert "kicad_mcp.schematic.connectivity_authoring" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.connectivity_authoring" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_connectivity_authoring" in boundaries.DOMAIN_MODULES


def test_connectivity_authoring_service_has_no_fastmcp_or_registry_dependency() -> None:
    service = boundaries.SRC_ROOT / "kicad_mcp" / "schematic" / "connectivity_authoring.py"
    imports = _imports(service)
    assert not any(name.startswith("mcp") for name in imports)
    assert "kicad_mcp.tools.schematic" not in imports


def test_connectivity_authoring_adapter_does_not_import_monolith() -> None:
    adapter = (
        boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_connectivity_authoring.py"
    )
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[
        "kicad_mcp.tools.schematic_connectivity_authoring"
    ] == ("kicad_mcp.tools.schematic",)


def test_connectivity_authoring_register_stays_below_300_lines() -> None:
    adapter = (
        boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_connectivity_authoring.py"
    )
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS[
        "kicad_mcp.tools.schematic_connectivity_authoring"
    ] == 300


def test_schematic_composition_root_delegates_connectivity_authoring() -> None:
    composition_root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic.py"
    source = composition_root.read_text(encoding="utf-8")
    assert "schematic_connectivity_authoring.register(" in source
    for nested_tool in (
        "def sch_add_pin_labels(",
        "def sch_route_wire_between_pins(",
        "def sch_add_missing_junctions(",
    ):
        assert nested_tool not in source
    assert "def run_auto_add_missing_junctions(" in source
