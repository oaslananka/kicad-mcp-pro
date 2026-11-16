"""Production isolation guard for the disposable MCP Apps issue #1220 fixture."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESEARCH = ROOT / "tests/research/mcp_apps_readonly"


def test_research_fixture_is_private_and_outside_pnpm_release_workspace() -> None:
    manifest = json.loads((RESEARCH / "package.json").read_text(encoding="utf-8"))
    assert manifest["private"] is True
    assert manifest["name"] == "@kicad-mcp-pro/mcp-apps-readonly-research"
    assert "mcp_apps_readonly" not in (ROOT / "pnpm-workspace.yaml").read_text(encoding="utf-8")
    assert (RESEARCH / "pnpm-workspace.yaml").is_file()


def test_production_mcp_python_tree_does_not_register_the_fixture() -> None:
    for file in (ROOT / "src/kicad_mcp").rglob("*.py"):
        content = file.read_text(encoding="utf-8")
        assert "ui://kicad-mcp-pro/readonly-review" not in content, file
        assert "review_kicad_fixture" not in content, file


def test_cloud_and_chatgpt_integration_do_not_expose_fixture_tool() -> None:
    for subtree in (ROOT / "apps/cloud/src", ROOT / "integrations/chatgpt-app"):
        if subtree.is_dir():
            for file in subtree.rglob("*"):
                if file.is_file() and file.suffix in {".py", ".ts", ".js", ".mjs", ".json"}:
                    assert "review_kicad_fixture" not in file.read_text(encoding="utf-8"), file
