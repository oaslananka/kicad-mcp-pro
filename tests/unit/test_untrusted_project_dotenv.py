"""Regression: a cloned project must never configure the MCP server executable."""

from __future__ import annotations

import ast
import os
import shlex
import sys
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / "src"
_PROCESS_ENV_KEYS = {"KICAD_CLI_PATH", "KICAD_API_TOKEN", "KICAD_API_SOCKET"}


def _inspect_cloned_project(
    project: Path,
    overrides: dict[str, str],
    *,
    probe_version: bool,
    send: Connection,
) -> None:
    """Run in a fresh, isolated interpreter without invoking a shell or test code."""
    try:
        os.chdir(project)
        for key in tuple(os.environ):
            if key.startswith("KICAD_MCP_") or key in _PROCESS_ENV_KEYS:
                os.environ.pop(key)
        os.environ.update(overrides)
        sys.path.insert(0, str(_SOURCE))
        # The real MCP entrypoint is not launched under pytest. The spawned
        # test module imports pytest only to declare tests in its parent.
        sys.modules.pop("pytest", None)

        from kicad_mcp.config import KiCadMCPConfig

        cfg = KiCadMCPConfig()
        result = {
            "cli": str(cfg.kicad_cli),
            "log": cfg.log_level,
            "mode": cfg.operating_mode,
            "experimental": cfg.enable_experimental_tools,
            "auth": cfg.auth_token,
        }
        if probe_version:
            from kicad_mcp.discovery import find_kicad_version

            result["version"] = find_kicad_version(cfg.kicad_cli)
        send.send({"result": result})
    except Exception as exc:
        send.send({"error": str(exc)})
    finally:
        send.close()


def _child_snapshot(
    project: Path, *, overrides: dict[str, str] | None = None, probe_version: bool = False
) -> dict[str, object]:
    """Inspect the real configuration in a spawned process and return its result."""
    context = get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_inspect_cloned_project,
        args=(project, overrides or {}),
        kwargs={"probe_version": probe_version, "send": send},
    )
    process.start()
    send.close()
    try:
        assert receive.poll(25), "Configuration probe timed out"
        result = receive.recv()
        process.join(timeout=5)
        assert process.exitcode == 0, "Configuration probe crashed"
        return result
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_cloned_project_dotenv_cannot_override_environment_cli(tmp_path: Path) -> None:
    project = tmp_path / "cloned-project"
    project.mkdir()
    (project / ".env").write_text(
        "KICAD_MCP_KICAD_CLI=bin/kicad-cli\nKICAD_MCP_LOG_LEVEL=CRITICAL\n",
        encoding="utf-8",
    )
    trusted = tmp_path / "trusted" / "kicad-cli"
    trusted.parent.mkdir()
    trusted.touch()
    result = _child_snapshot(project, overrides={"KICAD_CLI_PATH": str(trusted)})
    assert "error" not in result
    assert result["result"]["cli"] == str(trusted)
    assert result["result"]["log"] == "INFO"


@pytest.mark.skipif(os.name == "nt", reason="Unix executable fixture")
def test_server_info_cli_probe_cannot_execute_cloned_project_script(tmp_path: Path) -> None:
    project = tmp_path / "cloned-project"
    executable = project / "bin" / "kicad-cli"
    executable.parent.mkdir(parents=True)
    marker = tmp_path / "UNTRUSTED_SCRIPT_EXECUTED"
    executable.write_text(
        f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\nprintf 'KiCad 9.0.0\\n'\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    (project / ".env").write_text("KICAD_MCP_KICAD_CLI=bin/kicad-cli\n", encoding="utf-8")
    trusted = tmp_path / "owner-configured" / "kicad-cli"
    trusted.parent.mkdir()
    trusted.write_text("#!/bin/sh\nprintf 'KiCad 10.0.8\\n'\n", encoding="utf-8")
    trusted.chmod(0o755)

    output = _child_snapshot(
        project, overrides={"KICAD_CLI_PATH": str(trusted)}, probe_version=True
    )
    assert "error" not in output
    assert output["result"]["cli"] == str(trusted)
    assert output["result"]["version"] == "KiCad 10.0.8"
    assert not marker.exists(), "A read-only discovery call ran the cloned project's executable"


def test_cloned_project_dotenv_never_enables_sensitive_settings(tmp_path: Path) -> None:
    project = tmp_path / "cloned-project"
    project.mkdir()
    (project / ".env").write_text(
        "KICAD_MCP_OPERATING_MODE=experimental\n"
        "KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS=true\n"
        "KICAD_MCP_AUTH_TOKEN=attacker-controlled\n",
        encoding="utf-8",
    )
    result = _child_snapshot(project)
    assert "error" not in result
    assert result["result"]["mode"] == "readonly"
    assert result["result"]["experimental"] is False
    assert result["result"]["auth"] is None


@pytest.mark.parametrize("variable", ["KICAD_MCP_KICAD_CLI", "KICAD_CLI_PATH"])
def test_explicit_process_environment_cli_path_must_be_absolute(
    tmp_path: Path, variable: str
) -> None:
    project = tmp_path / "cloned-project"
    project.mkdir()
    output = _child_snapshot(project, overrides={variable: "bin/kicad-cli"})
    assert "absolute" in str(output.get("error", ""))


def test_cli_entrypoint_never_implicitly_loads_project_dotenv() -> None:
    """Static boundary check; hermetic even without the optional native MCP SDK."""
    tree = ast.parse((_SOURCE / "kicad_mcp" / "server.py").read_text(encoding="utf-8"))
    entrypoint = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    assert not any(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id == "load_dotenv")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "load_dotenv")
        )
        for node in ast.walk(entrypoint)
    ), "The CLI entrypoint must not import .env from an untrusted working directory"


def test_operator_cli_path_inside_active_project_is_rejected(tmp_path: Path) -> None:
    from kicad_mcp.config import KiCadMCPConfig

    project = tmp_path / "project"
    cli = project / "bin" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.touch()
    with pytest.raises(ValueError, match="outside the active project"):
        KiCadMCPConfig(project_dir=project, kicad_cli=cli)


@pytest.mark.skipif(os.name == "nt", reason="symlink privileges differ on Windows")
def test_operator_cli_symlink_into_project_is_rejected(tmp_path: Path) -> None:
    from kicad_mcp.config import KiCadMCPConfig

    project = tmp_path / "project"
    cli = project / "bin" / "kicad-cli"
    cli.parent.mkdir(parents=True)
    cli.touch()
    trusted_link = tmp_path / "trusted-link"
    trusted_link.symlink_to(cli)
    with pytest.raises(ValueError, match="outside the active project"):
        KiCadMCPConfig(project_dir=project, kicad_cli=trusted_link)


def test_relative_explicit_cli_constructor_rejected_before_file_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.config import KiCadMCPConfig

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="absolute executable path"):
        KiCadMCPConfig(kicad_cli=Path("bin/kicad-cli"))
