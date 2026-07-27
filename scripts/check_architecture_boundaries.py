"""Check incremental domain-boundary guards for the tool refactor.

This is intentionally narrow: it protects the first extracted helper modules from
sliding back into the schematic/PCB/server monoliths while the larger split
continues incrementally.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"

DOMAIN_MODULES = {
    "kicad_mcp.tools.schematic": SRC_ROOT / "kicad_mcp" / "tools" / "schematic.py",
    "kicad_mcp.companion.context": SRC_ROOT / "kicad_mcp" / "companion" / "context.py",
    "kicad_mcp.ipc.command_queue": SRC_ROOT / "kicad_mcp" / "ipc" / "command_queue.py",
    "kicad_mcp.models.contract_verifier": SRC_ROOT
    / "kicad_mcp"
    / "models"
    / "contract_verifier.py",
    "kicad_mcp.models.sch_transaction": SRC_ROOT / "kicad_mcp" / "models" / "sch_transaction.py",
    "kicad_mcp.models.visual_qa": SRC_ROOT / "kicad_mcp" / "models" / "visual_qa.py",
    "kicad_mcp.pcb.basic_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "basic_inspection.py",
    "kicad_mcp.pcb.file_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "file_inspection.py",
    "kicad_mcp.pcb.groups_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "groups_inspection.py",
    "kicad_mcp.pcb.origin_management": SRC_ROOT / "kicad_mcp" / "pcb" / "origin_management.py",
    "kicad_mcp.pcb.session_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "session_inspection.py",
    "kicad_mcp.pcb.title_block_management": SRC_ROOT
    / "kicad_mcp"
    / "pcb"
    / "title_block_management.py",
    "kicad_mcp.pcb.transaction_lifecycle": SRC_ROOT
    / "kicad_mcp"
    / "pcb"
    / "transaction_lifecycle.py",
    "kicad_mcp.schematic.back_annotation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "back_annotation.py",
    "kicad_mcp.schematic.basic_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "basic_authoring.py",
    "kicad_mcp.schematic.circuit_compilation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "circuit_compilation.py",
    "kicad_mcp.schematic.connectivity_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "connectivity_authoring.py",
    "kicad_mcp.schematic.destructive_edit": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "destructive_edit.py",
    "kicad_mcp.schematic.document_settings": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "document_settings.py",
    "kicad_mcp.schematic.hierarchy_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "hierarchy_authoring.py",
    "kicad_mcp.schematic.inspection": SRC_ROOT / "kicad_mcp" / "schematic" / "inspection.py",
    "kicad_mcp.schematic.lifecycle_authoring": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "lifecycle_authoring.py",
    "kicad_mcp.schematic.layout_automation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "layout_automation.py",
    "kicad_mcp.schematic.layout_inspection": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "layout_inspection.py",
    "kicad_mcp.schematic.rendering": SRC_ROOT / "kicad_mcp" / "schematic" / "rendering.py",
    "kicad_mcp.schematic.semantic_ir": SRC_ROOT / "kicad_mcp" / "schematic" / "semantic_ir.py",
    "kicad_mcp.schematic.symbol_mutation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "symbol_mutation.py",
    "kicad_mcp.schematic.template_catalog": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "template_catalog.py",
    "kicad_mcp.schematic.template_instantiation": SRC_ROOT
    / "kicad_mcp"
    / "schematic"
    / "template_instantiation.py",
    "kicad_mcp.schematic.topology": SRC_ROOT / "kicad_mcp" / "schematic" / "topology.py",
    "kicad_mcp.tools.pcb_groups_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_groups_inspection.py",
    "kicad_mcp.pcb.board_inspection": SRC_ROOT / "kicad_mcp" / "pcb" / "board_inspection.py",
    "kicad_mcp.tools.pcb_board_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_board_inspection.py",
    "kicad_mcp.tools.pcb_basic_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_basic_inspection.py",
    "kicad_mcp.tools.pcb_file_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_file_inspection.py",
    "kicad_mcp.tools.pcb_origin_management": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_origin_management.py",
    "kicad_mcp.tools.pcb_session_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_session_inspection.py",
    "kicad_mcp.tools.pcb_title_block_management": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_title_block_management.py",
    "kicad_mcp.tools.pcb_transaction_lifecycle": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "pcb_transaction_lifecycle.py",
    "kicad_mcp.tools.schematic_back_annotation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_back_annotation.py",
    "kicad_mcp.tools.schematic_basic_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_basic_authoring.py",
    "kicad_mcp.tools.schematic_circuit_compilation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_circuit_compilation.py",
    "kicad_mcp.tools.schematic_connectivity_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_connectivity_authoring.py",
    "kicad_mcp.tools.schematic_destructive_edit": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_destructive_edit.py",
    "kicad_mcp.tools.schematic_document_settings": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_document_settings.py",
    "kicad_mcp.tools.schematic_symbol_mutation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_symbol_mutation.py",
    "kicad_mcp.tools.schematic_template_catalog": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_catalog.py",
    "kicad_mcp.tools.schematic_template_instantiation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_template_instantiation.py",
    "kicad_mcp.tools.schematic_topology": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_topology.py",
    "kicad_mcp.tools.schematic_hierarchy_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_hierarchy_authoring.py",
    "kicad_mcp.tools.schematic_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_inspection.py",
    "kicad_mcp.tools.schematic_lifecycle_authoring": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_lifecycle_authoring.py",
    "kicad_mcp.tools.schematic_layout_automation": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_automation.py",
    "kicad_mcp.tools.schematic_layout_inspection": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_layout_inspection.py",
    "kicad_mcp.tools.schematic_rendering": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_rendering.py",
    "kicad_mcp.tools.schematic_semantic_ir": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_semantic_ir.py",
    "kicad_mcp.tools.schematic_constants": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_constants.py",
    "kicad_mcp.tools.schematic_transfer": SRC_ROOT
    / "kicad_mcp"
    / "tools"
    / "schematic_transfer.py",
}

PURE_HELPERS = {
    "kicad_mcp.companion.context",
    "kicad_mcp.ipc.command_queue",
    "kicad_mcp.models.contract_verifier",
    "kicad_mcp.models.sch_transaction",
    "kicad_mcp.models.visual_qa",
    "kicad_mcp.pcb.basic_inspection",
    "kicad_mcp.pcb.board_inspection",
    "kicad_mcp.pcb.file_inspection",
    "kicad_mcp.pcb.groups_inspection",
    "kicad_mcp.pcb.origin_management",
    "kicad_mcp.pcb.session_inspection",
    "kicad_mcp.pcb.title_block_management",
    "kicad_mcp.pcb.transaction_lifecycle",
    "kicad_mcp.schematic.back_annotation",
    "kicad_mcp.schematic.basic_authoring",
    "kicad_mcp.schematic.circuit_compilation",
    "kicad_mcp.schematic.connectivity_authoring",
    "kicad_mcp.schematic.destructive_edit",
    "kicad_mcp.schematic.document_settings",
    "kicad_mcp.schematic.hierarchy_authoring",
    "kicad_mcp.schematic.inspection",
    "kicad_mcp.schematic.lifecycle_authoring",
    "kicad_mcp.schematic.layout_automation",
    "kicad_mcp.schematic.layout_inspection",
    "kicad_mcp.schematic.rendering",
    "kicad_mcp.schematic.semantic_ir",
    "kicad_mcp.schematic.symbol_mutation",
    "kicad_mcp.schematic.template_catalog",
    "kicad_mcp.schematic.template_instantiation",
    "kicad_mcp.schematic.topology",
    "kicad_mcp.tools.schematic_constants",
}

FORBIDDEN_PURE_IMPORT_PREFIXES = (
    "kicad_mcp.server",
    "kicad_mcp.connection",
    "kicad_mcp.tools.pcb",
    "kicad_mcp.tools.schematic",
    "mcp",
    "pcbnew",
    "wx",
    "kipy",
)

ADAPTER_FORBIDDEN_IMPORT_PREFIXES = {
    "kicad_mcp.tools.pcb_basic_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_board_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_file_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_groups_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_origin_management": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_session_inspection": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_title_block_management": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.pcb_transaction_lifecycle": ("kicad_mcp.tools.pcb",),
    "kicad_mcp.tools.schematic_back_annotation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_basic_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_circuit_compilation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_connectivity_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_destructive_edit": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_document_settings": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_hierarchy_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_inspection": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_lifecycle_authoring": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_layout_automation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_layout_inspection": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_rendering": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_semantic_ir": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_symbol_mutation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_template_catalog": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_template_instantiation": ("kicad_mcp.tools.schematic",),
    "kicad_mcp.tools.schematic_topology": ("kicad_mcp.tools.schematic",),
}

REGISTER_LINE_LIMITS = {
    "kicad_mcp.tools.pcb_basic_inspection": 300,
    "kicad_mcp.tools.pcb_board_inspection": 300,
    "kicad_mcp.tools.pcb_file_inspection": 300,
    "kicad_mcp.tools.pcb_groups_inspection": 300,
    "kicad_mcp.tools.pcb_origin_management": 300,
    "kicad_mcp.tools.pcb_session_inspection": 300,
    "kicad_mcp.tools.pcb_title_block_management": 300,
    "kicad_mcp.tools.pcb_transaction_lifecycle": 300,
    "kicad_mcp.tools.schematic": 300,
    "kicad_mcp.tools.schematic_back_annotation": 300,
    "kicad_mcp.tools.schematic_basic_authoring": 300,
    "kicad_mcp.tools.schematic_circuit_compilation": 300,
    "kicad_mcp.tools.schematic_connectivity_authoring": 300,
    "kicad_mcp.tools.schematic_destructive_edit": 300,
    "kicad_mcp.tools.schematic_document_settings": 300,
    "kicad_mcp.tools.schematic_hierarchy_authoring": 300,
    "kicad_mcp.tools.schematic_inspection": 300,
    "kicad_mcp.tools.schematic_lifecycle_authoring": 300,
    "kicad_mcp.tools.schematic_layout_automation": 300,
    "kicad_mcp.tools.schematic_layout_inspection": 300,
    "kicad_mcp.tools.schematic_rendering": 300,
    "kicad_mcp.tools.schematic_semantic_ir": 300,
    "kicad_mcp.tools.schematic_symbol_mutation": 300,
    "kicad_mcp.tools.schematic_template_catalog": 300,
    "kicad_mcp.tools.schematic_template_instantiation": 300,
    "kicad_mcp.tools.schematic_topology": 300,
}


def _module_package(module_name: str) -> str:
    return module_name.rsplit(".", 1)[0]


def _resolve_import(module_name: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    package_parts = _module_package(module_name).split(".")
    if node.level > len(package_parts):
        return node.module or ""
    base = ".".join(package_parts[: len(package_parts) - node.level + 1])
    return f"{base}.{node.module}" if node.module else base


def _imports_for(module_name: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import(module_name, node)
            if resolved:
                imports.add(resolved)
    return imports


def _function_span(path: Path, function_name: str) -> int | None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    ]
    if len(matches) != 1:
        return None
    node = matches[0]
    if node.end_lineno is None:
        return None
    return node.end_lineno - node.lineno + 1


def _domain_target(import_name: str) -> str | None:
    for module_name in DOMAIN_MODULES:
        if import_name == module_name or import_name.startswith(f"{module_name}."):
            return module_name
    return None


def _find_cycle(graph: dict[str, set[str]]) -> list[str]:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        if node in visiting:
            index = stack.index(node)
            return [*stack[index:], node]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for child in sorted(graph[node]):
            cycle = visit(child)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return []

    for node in sorted(graph):
        cycle = visit(node)
        if cycle:
            return cycle
    return []


def main() -> int:
    errors: list[str] = []
    imports_by_module: dict[str, set[str]] = {}

    for module_name, path in DOMAIN_MODULES.items():
        if not path.exists():
            errors.append(f"Missing extracted module: {path.relative_to(REPO_ROOT)}")
            continue
        imports = _imports_for(module_name, path)
        imports_by_module[module_name] = imports
        if module_name in PURE_HELPERS:
            for import_name in sorted(imports):
                if import_name.startswith(FORBIDDEN_PURE_IMPORT_PREFIXES):
                    errors.append(f"{module_name} must stay pure; forbidden import: {import_name}")
        for import_name in sorted(imports):
            forbidden_prefixes = ADAPTER_FORBIDDEN_IMPORT_PREFIXES.get(module_name, ())
            if import_name.startswith(forbidden_prefixes):
                errors.append(
                    f"{module_name} must not import its composition-root monolith: {import_name}"
                )

        register_limit = REGISTER_LINE_LIMITS.get(module_name)
        if register_limit is not None:
            register_span = _function_span(path, "register")
            if register_span is None:
                errors.append(f"{module_name} must define exactly one top-level register()")
            elif register_span > register_limit:
                errors.append(
                    f"{module_name}.register spans {register_span} lines; limit is {register_limit}"
                )

    graph = {
        module_name: {
            target
            for import_name in imports
            for target in [_domain_target(import_name)]
            if target is not None and target != module_name
        }
        for module_name, imports in imports_by_module.items()
    }
    cycle = _find_cycle(graph)
    if cycle:
        errors.append("Import cycle among extracted domain modules: " + " -> ".join(cycle))

    if errors:
        print("Architecture boundary check failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Architecture boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
