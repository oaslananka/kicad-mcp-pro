"""Local-first quickstart regressions."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from kicad_mcp.server import app
from kicad_mcp.setup import detect_installed_agents, detect_kicad_project_directory


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

    async def fake_smoke(project: Path) -> tuple[bool, str]:
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
        }
    ]
    assert smoke == [tmp_path.resolve()]
    assert "Cloud is not required" in result.output
    assert "Local KiCad MCP is ready" in result.output


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
