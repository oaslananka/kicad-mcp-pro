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


def test_architecture_checker_tracks_hierarchy_authoring_modules() -> None:
    assert "kicad_mcp.schematic.hierarchy_authoring" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.hierarchy_authoring" in boundaries.PURE_HELPERS
    assert "kicad_mcp.tools.schematic_hierarchy_authoring" in boundaries.DOMAIN_MODULES


def test_hierarchy_authoring_adapter_does_not_import_monolith() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_hierarchy_authoring.py"
    assert "kicad_mcp.tools.schematic" not in _imports(adapter)
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[
        "kicad_mcp.tools.schematic_hierarchy_authoring"
    ] == ("kicad_mcp.tools.schematic",)


def test_hierarchy_authoring_register_stays_below_300_lines() -> None:
    adapter = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "schematic_hierarchy_authoring.py"
    assert _function_span(adapter, "register") <= 300
    assert boundaries.REGISTER_LINE_LIMITS["kicad_mcp.tools.schematic_hierarchy_authoring"] == 300


def test_architecture_checker_tracks_the_sheet_pin_module() -> None:
    assert "kicad_mcp.schematic.sheet_pins" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.schematic.sheet_pins" in boundaries.PURE_HELPERS


def test_sheet_pin_module_does_not_depend_on_kicad_sch_api() -> None:
    # The whole point of the text-splice write path: a kicad-sch-api round trip
    # drops title_block comments, so this module must never reach for it.
    #
    # boundaries.FORBIDDEN_PURE_IMPORT_PREFIXES does NOT include "kicad_sch_api"
    # -- that tuple is shared by every module in PURE_HELPERS, some of which may
    # legitimately want it for pure parsing, so it is not this module's policy
    # to set. This test is therefore the only thing actually enforcing the ban
    # on this module; registering in PURE_HELPERS does not provide it.
    module = boundaries.SRC_ROOT / "kicad_mcp" / "schematic" / "sheet_pins.py"
    imports = _imports(module)
    assert not any(name.startswith("kicad_sch_api") for name in imports)
    assert not any(name.startswith("kicad_mcp.tools") for name in imports)
