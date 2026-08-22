from __future__ import annotations

import ast
from pathlib import Path

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.errors import UnsafePathError
from kicad_mcp.tools import routing_rules, validation, variants

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


def test_routing_rule_write_rejects_symlink_escape(sample_project: Path, tmp_path: Path) -> None:
    rules_path = sample_project / "demo.kicad_dru"
    outside = tmp_path / "outside.kicad_dru"
    outside.write_text("(rules)\n", encoding="utf-8")
    rules_path.unlink()
    rules_path.symlink_to(outside)

    with pytest.raises(UnsafePathError):
        routing_rules._write_rule("min-width", '(rule "min-width")')

    assert outside.read_text(encoding="utf-8") == "(rules)\n"


def test_drc_state_write_rejects_symlinked_sidecar_directory(
    sample_project: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside-state"
    outside.mkdir()
    sidecar = sample_project / ".kicad-mcp"
    sidecar.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        validation._save_drc_state({"enabled": {}, "severity": {}})

    assert not (outside / "drc_rules_state.json").exists()


def test_variant_state_write_rejects_symlinked_sidecar_directory(
    sample_project: Path,
    tmp_path: Path,
) -> None:
    (sample_project / "demo.kicad_pro").unlink()
    reset_config()
    outside = tmp_path / "outside-variants"
    outside.mkdir()
    sidecar = sample_project / ".kicad-mcp"
    sidecar.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        variants._save_state(
            {
                "default_variant": "default",
                "active_variant": "default",
                "variants": {"default": {"overrides": {}}},
            }
        )

    assert not (outside / "variants.json").exists()


def test_board_design_rule_write_routes_through_safe_writer() -> None:
    path = REPO_ROOT / "src" / "kicad_mcp" / "tools" / "pcb.py"
    calls = _function_calls(path, "pcb_set_design_rules")

    assert "_write_rules_content" in calls


@pytest.mark.parametrize("function_name", ["drc_rule_create", "drc_rule_delete", "drc_rule_enable"])
def test_validation_rule_writes_route_through_safe_writer(function_name: str) -> None:
    path = REPO_ROOT / "src" / "kicad_mcp" / "tools" / "validation.py"
    calls = _function_calls(path, function_name)

    assert "_write_rules_content" in calls
