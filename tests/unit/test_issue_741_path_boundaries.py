from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _function_calls(path: Path, function_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
    )
    calls: list[str] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            calls.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            calls.append(node.func.attr)
    return calls


def test_embedded_file_tool_routes_source_through_safe_resolver() -> None:
    path = REPO_ROOT / "src" / "kicad_mcp" / "tools" / "embedded_files.py"
    calls = _function_calls(path, "project_embed_file")

    assert "_resolve_embed_source" in calls


def test_3d_footprint_lookup_validates_components_and_roots_candidates() -> None:
    path = REPO_ROOT / "src" / "kicad_mcp" / "tools" / "three_d_models.py"
    calls = _function_calls(path, "_find_footprint_file")

    assert calls.count("_safe_library_component") == 2
    assert calls.count("resolve_under") == 3


def test_3d_bulk_assignment_validates_library_and_roots_iterated_files() -> None:
    path = REPO_ROOT / "src" / "kicad_mcp" / "tools" / "three_d_models.py"
    calls = _function_calls(path, "lib_bulk_assign_3d_models")

    assert "_safe_library_component" in calls
    assert calls.count("resolve_under") >= 3
