#!/usr/bin/env python3
"""Fail when deprecated KiCad SWIG ``pcbnew`` bindings are imported or used.

KiCad 9/10 keep ``pcbnew`` around only as a legacy compatibility surface and
KiCad 11 is expected to remove it. KiCad MCP Pro must keep runtime code on the
supported IPC/CLI surfaces instead of adding new SWIG dependencies.
"""

from __future__ import annotations

import ast
import fnmatch
import sys
from pathlib import Path

import yaml

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT
MATRIX_PATH = REPO_ROOT / "compatibility.yaml"
SCAN_DIRS = tuple(
    d
    for d in (REPO_ROOT / "apps", MCP_ROOT / "src", MCP_ROOT / "scripts", MCP_ROOT / "tests")
    if d.is_dir()
)
DEFAULT_ALLOWED_PATHS = ("scripts/check_no_pcbnew.py",)


def _is_pcbnew_module(module_name: str | None) -> bool:
    return (
        module_name is not None
        and bool(module_name)
        and (module_name == "pcbnew" or module_name.startswith("pcbnew."))
    )


def _repo_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def _allowed_path_patterns() -> tuple[str, ...]:
    if not MATRIX_PATH.exists():
        return DEFAULT_ALLOWED_PATHS
    data = yaml.safe_load(MATRIX_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return DEFAULT_ALLOWED_PATHS
    readiness = data.get("kicadIpcReadiness")
    if not isinstance(readiness, dict):
        return DEFAULT_ALLOWED_PATHS
    direct_imports = readiness.get("directPcbnewImports", {})
    allowed = direct_imports.get("allowedPaths") if isinstance(direct_imports, dict) else None
    if not isinstance(allowed, list):
        return DEFAULT_ALLOWED_PATHS
    return tuple(pattern for pattern in allowed if isinstance(pattern, str) and pattern)


def _is_allowed(path: Path, patterns: tuple[str, ...]) -> bool:
    relative = _repo_relative(path)
    return any(fnmatch.fnmatchcase(relative, pattern) for pattern in patterns)


def _node_pcbnew_findings(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return ["deprecated pcbnew import" for alias in node.names if _is_pcbnew_module(alias.name)]
    if isinstance(node, ast.ImportFrom) and _is_pcbnew_module(node.module):
        return ["deprecated pcbnew import"]
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "pcbnew"
    ):
        return ["deprecated pcbnew attribute access"]
    return []


def _violations(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path}: cannot parse Python file: {exc}"]

    findings: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute)):
            findings.extend(
                f"{path}:{node.lineno}: {finding}" for finding in _node_pcbnew_findings(node)
            )
    return findings


def _python_files() -> list[Path]:
    files: list[Path] = []
    allowed = _allowed_path_patterns()
    for directory in SCAN_DIRS:
        if directory.exists():
            files.extend(path for path in directory.rglob("*.py") if not _is_allowed(path, allowed))
    return sorted(files)


def main() -> int:
    findings: list[str] = []
    for path in _python_files():
        findings.extend(_violations(path))

    if findings:
        print("Deprecated KiCad pcbnew/SWIG usage detected:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        print(
            "Use kicad-cli, kicad-python IPC, or an explicit adapter boundary instead.",
            file=sys.stderr,
        )
        return 1

    print("No deprecated pcbnew/SWIG usage detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
