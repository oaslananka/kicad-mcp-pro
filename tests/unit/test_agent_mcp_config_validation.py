"""Regression tests for local agent MCP example-file validation."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "integrations/common/validate-mcp-config.py"


def _check(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_all_checked_in_examples_validate_in_the_correct_format() -> None:
    result = _check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "✓ config.toml.example: valid" in result.stdout


def test_codex_example_with_toml_example_suffix_validates_via_path() -> None:
    result = _check("--path", "integrations/codex/config.toml.example")
    assert result.returncode == 0, result.stdout + result.stderr


def test_invalid_toml_example_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text("[mcp_servers.kicad\ncommand = 'uvx'\n", encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "Invalid TOML" in result.stdout


def test_toml_without_executable_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text("[mcp_servers.kicad]\nargs = ['kicad-mcp-pro']\n", encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "missing command/url" in result.stdout


def test_toml_rejects_malformed_command_arguments(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[mcp_servers.kicad]\ncommand = 'uvx'\nargs = 'not-an-array'\n",
        encoding="utf-8",
    )
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "invalid args" in result.stdout


def test_toml_rejects_non_string_environment_values(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text(
        "[mcp_servers.kicad]\ncommand = 'uvx'\n"
        "[mcp_servers.kicad.env]\nKICAD_MCP_OPERATING_MODE = 42\n",
        encoding="utf-8",
    )
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "invalid env" in result.stdout


def test_toml_accepts_supported_remote_mcp_endpoint(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        "[mcp_servers.kicad]\nurl = 'http://127.0.0.1:8765/mcp'\n",
        encoding="utf-8",
    )
    result = _check("--path", str(path))
    assert result.returncode == 0, result.stdout


def test_toml_empty_command_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text("[mcp_servers.kicad]\ncommand = '   '\n", encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "missing command/url" in result.stdout


def test_toml_malformed_server_table_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text("mcp_servers = { kicad = 'not-a-table' }\n", encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "expected server table" in result.stdout


def test_toml_without_mcp_server_table_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text("[unrelated]\nname = 'test'\n", encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert "missing mcp_servers" in result.stdout


def test_json_examples_remain_json_validated() -> None:
    result = _check("--path", "integrations/claude-code/.mcp.json.example")
    assert result.returncode == 0
