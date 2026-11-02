"""Local-first quickstart regressions."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kicad_mcp.server import app
from kicad_mcp.setup import detect_installed_agents, detect_kicad_project_directory


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    for name in ("OPENCODE", "CLAUDE_CODE", "CURSOR", "VSCODE_MCP", "CODEX", "GEMINI_CLI"):
        monkeypatch.delenv(name, raising=False)


def test_project_detection_is_shallow_and_requires_a_real_kicad_file(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "board.kicad_pcb").write_text("(kicad_pcb)", encoding="utf-8")
    assert detect_kicad_project_directory(tmp_path) is None
    assert detect_kicad_project_directory(nested) == nested.resolve()


def test_agent_detection_uses_available_cli_executables(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.setup.shutil.which", lambda name: "/usr/bin/codex" if name == "codex" else None
    )
    monkeypatch.setattr("kicad_mcp.server._detect_client", lambda: None)
    assert detect_installed_agents() == ["codex"]


def test_quickstart_installs_readonly_and_runs_stdio_smoke(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    installed: list[dict[str, object]] = []
    smoke: list[Path] = []

    def fake_setup_agent(agent: str, **kwargs: object) -> str:
        installed.append({"agent": agent, **kwargs})
        return "✓ Config written to /tmp/cursor-mcp.json"

    async def fake_smoke(project: Path, **kwargs: object) -> tuple[bool, str]:
        assert kwargs == {"agent": "cursor", "scope": "project"}
        smoke.append(project)
        return True, "MCP stdio initialized; kicad_get_server_info succeeded."

    monkeypatch.setattr("kicad_mcp.setup.setup_agent", fake_setup_agent)
    monkeypatch.setattr("kicad_mcp.setup.run_local_mcp_smoke", fake_smoke)

    result = CliRunner().invoke(
        app,
        ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    assert installed == [
        {
            "agent": "cursor",
            "project_dir": str(tmp_path.resolve()),
            "mode": "readonly",
            "write": True,
            "scope": "project",
            "transport": "stdio",
            "stdio_command": __import__("shutil").which("uvx"),
        }
    ]
    assert smoke == [tmp_path.resolve()]
    assert "Cloud is not required" in result.output
    assert "MCP launch verified" in result.output
    assert (tmp_path / ".cursor/skills/pcb-design/SKILL.md").is_file()


def test_quickstart_rejects_non_project_without_writing(tmp_path: Path, monkeypatch) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> str:
        raise AssertionError("must not write configuration for an invalid project")

    monkeypatch.setattr("kicad_mcp.setup.setup_agent", fail_if_called)
    result = CliRunner().invoke(
        app,
        ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "does not contain a KiCad project" in result.output


def test_quickstart_rejects_remote_only_agent(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    result = CliRunner().invoke(
        app,
        ["quickstart", "--agent", "chatgpt", "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "supported local agent" in result.output


def test_agent_detection_prefers_embedded_agent_environment(monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: None)
    monkeypatch.setenv("CODEX", "1")
    assert detect_installed_agents() == ["codex"]


def test_missing_uvx_never_writes_config_or_reports_ready(tmp_path, monkeypatch) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")
    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: None)
    result = CliRunner().invoke(
        app, ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "uv" in result.output
    assert not (tmp_path / ".cursor").exists()


@pytest.mark.anyio
async def test_saved_launcher_failure_cannot_be_hidden_by_current_python(
    tmp_path, monkeypatch
) -> None:
    from kicad_mcp.setup import run_local_mcp_smoke, setup_agent

    setup_agent("cursor", str(tmp_path), write=True, scope="project")
    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: None)
    ok, message = await run_local_mcp_smoke(tmp_path, agent="cursor", scope="project")
    assert not ok
    assert "uvx" in message


@pytest.mark.parametrize(
    "agent", ["codex", "cursor", "vscode", "opencode", "gemini", "claude-code"]
)
def test_saved_stdio_parameters_match_each_native_config(tmp_path, monkeypatch, agent) -> None:
    from kicad_mcp.setup import AGENTS, configured_stdio_parameters, setup_agent

    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: "/trusted/uvx")
    scope = "project" if "project" in AGENTS[agent].supports_scope else "user"
    setup_agent(agent, str(tmp_path), write=True, scope=scope, stdio_command="/trusted/uvx")
    parameters = configured_stdio_parameters(tmp_path, agent=agent, scope=scope)
    assert parameters.command == "/trusted/uvx"
    assert parameters.args[0] == "kicad-mcp-pro"
    assert parameters.env["KICAD_MCP_PROJECT_DIR"] == str(tmp_path)
    assert parameters.env["KICAD_MCP_OPERATING_MODE"] == "readonly"
    assert parameters.env["KICAD_MCP_TRANSPORT"] == "stdio"
    assert parameters.cwd == str(tmp_path)


def test_smoke_refuses_changed_saved_launcher(tmp_path) -> None:
    import json

    from kicad_mcp.setup import configured_stdio_parameters, setup_agent

    setup_agent("cursor", str(tmp_path), write=True, scope="project")
    path = tmp_path / ".cursor/mcp.json"
    config = json.loads(path.read_text())
    config["mcpServers"]["kicad"]["command"] = "unexpected-command"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="saved|changed|match"):
        configured_stdio_parameters(tmp_path, agent="cursor", scope="project")


def test_conflicting_skill_fails_before_config_write(tmp_path) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")
    existing = tmp_path / ".cursor/skills/pcb-design/SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("My review")
    result = CliRunner().invoke(
        app, ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "--no-skills" in result.output
    assert not (tmp_path / ".cursor/mcp.json").exists()
    assert existing.read_text() == "My review"


def test_no_skills_preserves_existing_skill_and_reports_verification_limit(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")
    existing = tmp_path / ".cursor/skills/pcb-design/SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("My review")

    async def smoke(project, **kwargs: object) -> None:
        return True, "Verified saved launch command"

    monkeypatch.setattr("kicad_mcp.setup.run_local_mcp_smoke", smoke)
    result = CliRunner().invoke(
        app, ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path), "--no-skills"]
    )
    assert result.exit_code == 0, result.output
    assert existing.read_text() == "My review"
    assert "MCP launch verified" in result.output
    assert "actual agent" in result.output


def test_smoke_failure_reports_saved_config_without_installing_skills(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")

    async def smoke(project, **kwargs: object) -> None:
        return False, "Saved launcher failed"

    monkeypatch.setattr("kicad_mcp.setup.run_local_mcp_smoke", smoke)
    result = CliRunner().invoke(
        app, ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert "saved" in result.output
    assert (tmp_path / ".cursor/mcp.json").is_file()
    assert not (tmp_path / ".cursor/skills").exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "behavior", ["ok", "missing-tool", "tool-error", "empty", "transport-error"]
)
async def test_smoke_checks_protocol_outcomes_from_saved_launch(
    tmp_path, monkeypatch, behavior
) -> None:
    from kicad_mcp.setup import run_local_mcp_smoke, setup_agent

    setup_agent("cursor", str(tmp_path), write=True, scope="project")
    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: "/trusted/uvx")

    @asynccontextmanager
    async def transport(parameters):
        assert parameters.command == "/trusted/uvx"
        yield (object(), object())

    class Session:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def initialize(self) -> None:
            if behavior == "transport-error":
                raise RuntimeError("PRIVATE_TOKEN_DO_NOT_PRINT")

        async def list_tools(self):
            return SimpleNamespace(
                tools=[]
                if behavior == "missing-tool"
                else [SimpleNamespace(name="kicad_get_server_info")]
            )

        async def call_tool(self, name, arguments):
            assert name == "kicad_get_server_info"
            assert arguments == {}
            return SimpleNamespace(
                is_error=behavior == "tool-error", content=[] if behavior == "empty" else [object()]
            )

    monkeypatch.setattr("mcp.client.stdio.stdio_client", transport)
    monkeypatch.setattr("mcp.ClientSession", Session)
    ok, message = await run_local_mcp_smoke(tmp_path, agent="cursor", scope="project")
    assert ok == (behavior == "ok")
    assert "PRIVATE_TOKEN" not in message


def test_skill_cli_install_status_and_remove(tmp_path) -> None:
    arguments = ["--agent", "cursor", "--project-dir", str(tmp_path)]
    runner = CliRunner()
    installed = runner.invoke(app, ["skills", "install", *arguments])
    assert installed.exit_code == 0, installed.output
    status = runner.invoke(app, ["skills", "status", *arguments])
    assert status.exit_code == 0, status.output
    assert "7/7" in status.output
    removed = runner.invoke(app, ["skills", "remove", *arguments])
    assert removed.exit_code == 0, removed.output
    assert "Removed 7" in removed.output


@pytest.mark.parametrize(
    "arguments",
    [
        ["unknown", "--agent", "cursor"],
        ["install", "--agent", "chatgpt"],
        ["install", "--agent", "claude-desktop"],
        ["install", "--agent", "cursor", "--scope", "global"],
    ],
)
def test_skill_cli_rejects_invalid_selection(arguments) -> None:
    assert CliRunner().invoke(app, ["skills", *arguments]).exit_code != 0


@pytest.mark.parametrize("detected", [[], ["cursor"], ["cursor", "codex"]])
def test_quickstart_selects_or_prompts_for_detected_agent(tmp_path, monkeypatch, detected) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")
    monkeypatch.setattr("kicad_mcp.setup.detect_installed_agents", lambda: detected)

    async def smoke(project, **kwargs: object):
        return True, "Launch checked"

    monkeypatch.setattr("kicad_mcp.setup.run_local_mcp_smoke", smoke)
    result = CliRunner().invoke(
        app, ["quickstart", "--project-dir", str(tmp_path)], input="cursor\n"
    )
    assert result.exit_code == 0, result.output
    assert "Agent: cursor" in result.output


@pytest.mark.parametrize("valid", [True, False])
def test_quickstart_prompts_for_missing_project(tmp_path, monkeypatch, valid) -> None:
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "chosen"
    project.mkdir()
    if valid:
        (project / "board.kicad_pro").write_text("{}")

    async def smoke(project, **kwargs: object):
        return True, "Launch checked"

    monkeypatch.setattr("kicad_mcp.setup.run_local_mcp_smoke", smoke)
    result = CliRunner().invoke(app, ["quickstart", "--agent", "cursor"], input=str(project) + "\n")
    assert result.exit_code == (0 if valid else 2), result.output


def test_quickstart_rejects_invalid_scope_before_writing(tmp_path) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}")
    result = CliRunner().invoke(
        app,
        ["quickstart", "--agent", "cursor", "--project-dir", str(tmp_path), "--scope", "invalid"],
    )
    assert result.exit_code == 2
    assert not (tmp_path / ".cursor").exists()
