from __future__ import annotations

import ast

from scripts import check_architecture_boundaries as boundaries

DOMAIN = "kicad_mcp.project.reporting"
ADAPTER = "kicad_mcp.tools.project_reporting"
PROJECT_ROOT = "kicad_mcp.tools.project"


def test_architecture_checker_tracks_reporting_modules() -> None:
    assert DOMAIN in boundaries.DOMAIN_MODULES
    assert DOMAIN in boundaries.PURE_HELPERS
    assert ADAPTER in boundaries.DOMAIN_MODULES
    assert boundaries.ADAPTER_FORBIDDEN_IMPORT_PREFIXES[ADAPTER] == (PROJECT_ROOT,)
    assert boundaries.REGISTER_LINE_LIMITS[ADAPTER] == 55


def test_reporting_service_and_adapter_do_not_back_import_tool_ownership() -> None:
    forbidden_by_module = {
        DOMAIN: {
            PROJECT_ROOT,
            "kicad_mcp.tools.validation",
            "kicad_mcp.tools.fixers",
            "kicad_mcp.resources.gate_history",
            "mcp",
        },
        ADAPTER: {PROJECT_ROOT},
    }
    for module_name, forbidden in forbidden_by_module.items():
        path = boundaries.DOMAIN_MODULES.get(module_name)
        assert path is not None
        imports = boundaries._imports_for(module_name, path)
        for forbidden_import in forbidden:
            assert not any(
                imported == forbidden_import or imported.startswith(f"{forbidden_import}.")
                for imported in imports
            )


def test_reporting_adapter_register_stays_bounded() -> None:
    path = boundaries.DOMAIN_MODULES.get(ADAPTER)
    assert path is not None
    span = boundaries._function_span(path, "register")
    assert span is not None
    assert span <= 55


def test_project_root_no_longer_owns_reporting_tools() -> None:
    root = boundaries.SRC_ROOT / "kicad_mcp" / "tools" / "project.py"
    tree = ast.parse(root.read_text(encoding="utf-8"), filename=str(root))
    register_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register"
    )
    nested_names = {
        node.name
        for node in register_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "project_gate_trend" not in nested_names
    assert "project_design_report" not in nested_names


def test_project_root_reexports_design_report_payload_from_reporting_domain() -> None:
    from kicad_mcp.project.reporting import DesignReportPayload as DomainPayload
    from kicad_mcp.tools.project import DesignReportPayload as CompatibilityPayload

    assert CompatibilityPayload is DomainPayload
