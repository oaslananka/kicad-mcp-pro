"""Regression tests for local agent MCP example-file validation."""

from __future__ import annotations

import io
import runpy
import sys
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "integrations/common/validate-mcp-config.py"
VALIDATOR_MAIN = runpy.run_path(str(VALIDATOR))["main"]


@dataclass(frozen=True)
class _Result:
    returncode: int
    stdout: str
    stderr: str = ""


def _check(*arguments: str) -> _Result:
    """Call the genuine CLI main under a captured stdout, no child process."""
    output = io.StringIO()
    with patch.object(sys, "argv", ["validate-mcp-config.py", *arguments]):
        with redirect_stdout(output):
            code = VALIDATOR_MAIN()
    return _Result(returncode=code, stdout=output.getvalue())


def test_all_checked_in_examples_validate_in_the_correct_format() -> None:
    result = _check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS config.toml.example: valid" in result.stdout


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


def test_validator_output_is_safe_for_windows_cp1252() -> None:
    """The actual report must contain no non-CP1252 console symbols."""
    result = _check()
    assert result.returncode == 0
    result.stdout.encode("cp1252", errors="strict")
    assert result.stdout.startswith("PASS ")


@pytest.mark.parametrize(
    ("server_toml", "reason"),
    [
        ("command = 'uvx'\nurl = 'https://example.org/mcp'\n", "command and url"),
        ("url = 'https://example.org/mcp'\nargs = []\n", "URL transport"),
        (
            "url = 'https://example.org/mcp'\n[ mcp_servers.kicad.env ]\nKEY = 'v'\n",
            "URL transport",
        ),
        ("url = 'https://example.org/mcp'\nenv_vars = ['KEY']\n", "URL transport"),
        ("url = 'https://example.org/mcp'\ncwd = '/tmp'\n", "URL transport"),
    ],
)
def test_codex_rejects_mixed_transport_fields(
    tmp_path: Path, server_toml: str, reason: str
) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text("[mcp_servers.kicad]\n" + server_toml, encoding="utf-8")
    result = _check("--path", str(path))
    assert result.returncode != 0
    assert reason in result.stdout


def test_codex_accepts_stdio_command_and_args(tmp_path: Path) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text(
        "[mcp_servers.kicad]\ncommand = 'uvx'\nargs = ['kicad-mcp-pro']\n",
        encoding="utf-8",
    )
    assert _check("--path", str(path)).returncode == 0


@pytest.mark.parametrize(
    "values",
    [
        "[42]",
        "{name = 'API_KEY'}",
        "[{name = 42}]",
        "[{name = 'API_KEY', source = 'wrong'}]",
        "[{name = 'API_KEY', extra = 'invalid'}]",
    ],
)
def test_codex_stdio_rejects_invalid_env_vars(tmp_path: Path, values: str) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text(
        "[mcp_servers.kicad]\ncommand = 'uvx'\nenv_vars = " + values + "\n",
        encoding="utf-8",
    )
    result = _check("--path", str(path))
    assert result.returncode == 1
    assert "invalid env_vars" in result.stdout


@pytest.mark.parametrize(
    "values",
    [
        "['API_KEY', 'OTHER']",
        "[{name = 'API_KEY'}]",
        "[{name = 'API_KEY', source = 'local'}]",
        "[{name = 'API_KEY', source = 'remote'}]",
    ],
)
def test_codex_stdio_accepts_supported_env_vars(tmp_path: Path, values: str) -> None:
    path = tmp_path / "config.toml.example"
    path.write_text(
        "[mcp_servers.kicad]\ncommand = 'uvx'\nenv_vars = " + values + "\n",
        encoding="utf-8",
    )
    result = _check("--path", str(path))
    assert result.returncode == 0, result.stdout
