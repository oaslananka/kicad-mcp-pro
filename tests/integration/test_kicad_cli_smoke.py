from __future__ import annotations

import os
from pathlib import Path

import pytest

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.discovery import find_kicad_version
from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

FIXTURE_PROJECT = Path("tests/fixtures/benchmark_projects/pass_minimal_mcu_board")


@pytest.fixture
def kicad_cli_path() -> Path:
    """Fixture that returns the KiCad CLI path or skips if not configured."""
    cli_env = os.environ.get("KICAD_MCP_KICAD_CLI") or os.environ.get("KICAD_CLI_PATH")
    if not cli_env:
        pytest.skip("KICAD_MCP_KICAD_CLI is not set")

    path = Path(cli_env).expanduser()
    if not path.exists():
        pytest.skip(f"kicad-cli not found at {path}")

    return path


@pytest.mark.anyio
async def test_kicad_cli_version_10(kicad_cli_path: Path) -> None:
    """Verify that the configured KiCad CLI reports version 10."""
    version = find_kicad_version(kicad_cli_path)
    assert version is not None, "Failed to discover KiCad version"

    # version string can be "10.0.0", "10.0.1-rc1", etc.
    # or even more complex like "10.0.0-3.fc40"
    major = version.split(".")[0]
    assert major == "10", f"Expected KiCad major version 10, got {version}"


@pytest.mark.anyio
async def test_kicad_cli_board_stats_smoke(
    kicad_cli_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Run real KiCad CLI to export board stats on a fixture project."""
    # Setup workspace and project
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    project_dir = workspace / "project"
    project_dir.mkdir()

    # Copy fixture files
    for f in FIXTURE_PROJECT.glob("demo.*"):
        (project_dir / f.name).write_bytes(f.read_bytes())

    output_dir = workspace / "output"

    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", str(kicad_cli_path))
    monkeypatch.setenv("KICAD_MCP_WORKSPACE_ROOT", str(workspace))
    monkeypatch.setenv("KICAD_MCP_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("KICAD_MCP_OUTPUT_DIR", str(output_dir))

    reset_config()
    cfg = get_config()
    assert cfg.kicad_cli == kicad_cli_path
    assert cfg.workspace_root == workspace

    server = build_server("full")

    # We must explicitly set the project to ensure all internal state is updated
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project_dir)})

    # Run the tool
    stats_text = await call_tool_text(server, "get_board_stats", {})

    # Assertions
    assert "Board Statistics" in stats_text or "Component Count" in stats_text

    stats_file = output_dir / "board_stats.txt"
    assert stats_file.exists(), f"Stats file {stats_file} was not created"
    assert stats_file.read_text(encoding="utf-8").strip() != ""

    # Additional check: ensure it was written where we expected
    assert stats_file.parent == output_dir
