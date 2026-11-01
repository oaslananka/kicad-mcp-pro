"""Guard against accidentally registering the operator-only Cloud CLIs as MCP tools.

This checks direct imports/calls in the server and tool modules, not all
possible shell/agent privileges. An agent with separate OS execution access
still needs an independently enforced local trust boundary.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "kicad_mcp"
_CLI_MODULES = frozenset(
    {
        "cloud_once",
        "cloud_pair",
        "cloud_outbound_handshake",
        "cloud_readonly_boundary",
        "cloud_read_dispatch",
        "cloud_device_proofs",
    }
)


def _direct_cli_imports(module: ast.AST) -> list[str]:
    """Find both absolute and relative imports into privileged Cloud modules."""
    forbidden: list[str] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] in _CLI_MODULES:
                    forbidden.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            imported = node.module or ""
            if imported.rsplit(".", 1)[-1] in _CLI_MODULES:
                forbidden.append(imported)
            if imported in {"", "kicad_mcp"} and (node.level or imported == "kicad_mcp"):
                for alias in node.names:
                    if alias.name in _CLI_MODULES:
                        forbidden.append(alias.name)
    return forbidden


@pytest.mark.parametrize(
    "sample",
    [
        "import kicad_mcp.cloud_once",
        "from kicad_mcp import cloud_pair",
        "from .cloud_once import main",
        "from ..cloud_read_dispatch import LocalReadDispatch",
        "from cloud_readonly_boundary import inspect_readonly",
        "from . import cloud_device_proofs",
    ],
)
def test_agent_tool_boundary_guard_detects_direct_imports(sample: str) -> None:
    assert _direct_cli_imports(ast.parse(sample))


@pytest.mark.parametrize(
    "source",
    [_SOURCE_ROOT / "server.py", *sorted((_SOURCE_ROOT / "tools").rglob("*.py"))],
)
def test_operator_only_cloud_cli_is_not_imported_as_agent_tool(source: Path) -> None:
    """Only explicit operator processes can currently initiate Cloud CLI work."""
    module = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    forbidden = _direct_cli_imports(module)
    assert not forbidden, f"{source.relative_to(_SOURCE_ROOT)} imports {forbidden}"
