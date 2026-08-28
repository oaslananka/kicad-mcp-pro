"""Regression tests for PCM-era guided onboarding safety (issue #731)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from kicad_mcp.server import app
from kicad_mcp.setup import generate_config, setup_agent, write_config


def test_claude_code_preview_never_writes_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, ...]] = []

    def fail_if_called(*args: object, **kwargs: object) -> tuple[str, bool]:
        calls.append((*args, kwargs))
        return "mutated", True

    monkeypatch.setattr("kicad_mcp.setup.write_config", fail_if_called)

    result = setup_agent("claude-code", project_dir="/workspace/project", write=False)

    assert calls == []
    assert '"mcpServers"' in result
    assert '"kicad"' in result


def test_init_defaults_to_preview_without_explicit_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def fake_setup_agent(*args: object, **kwargs: object) -> str:
        calls.append(bool(kwargs["write"]))
        return "preview"

    monkeypatch.setattr("kicad_mcp.setup.setup_agent", fake_setup_agent)
    monkeypatch.setattr("kicad_mcp.discovery.discover_kicad_cli", lambda: Path("kicad-cli"))
    monkeypatch.setattr("kicad_mcp.server.find_kicad_version", lambda _: "KiCad 10.0.5")
    monkeypatch.setattr(
        "kicad_mcp.server.build_health_report",
        lambda: SimpleNamespace(ok=True, status="ok", checks=[]),
    )

    result = CliRunner().invoke(
        app,
        ["init", "--project-dir", str(tmp_path), "--agent", "cursor"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [False]
    assert "Config:  Generated" in result.output


def test_json_write_preserves_unrelated_config_and_creates_restorable_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    original = {
        "theme": "dark",
        "mcpServers": {
            "other": {"command": "other-tool", "args": ["--safe"]},
            "kicad": {"command": "old-kicad", "args": []},
        },
    }
    path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)
    generated, _ = generate_config("cursor", "/workspace/board", "readonly")

    path_str, ok = write_config("cursor", generated, "project")

    assert ok, path_str
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["theme"] == "dark"
    assert updated["mcpServers"]["other"] == original["mcpServers"]["other"]
    assert updated["mcpServers"]["kicad"]["command"] == "uvx"
    backups = sorted(tmp_path.glob("mcp.json.*.kicad-mcp.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_codex_write_replaces_only_owned_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.toml"
    original = """# keep this comment
[model]
name = "gpt-example"

[mcp_servers.other]
command = "other"

[mcp_servers.kicad]
command = "old"
args = ["legacy"]

[mcp_servers.kicad.env]
OLD = "1"

[features]
foo = true
"""
    path.write_text(original, encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)
    generated, _ = generate_config("codex", "/workspace/board", "readonly")

    path_str, ok = write_config("codex", generated, "user")

    assert ok, path_str
    updated = path.read_text(encoding="utf-8")
    assert "# keep this comment" in updated
    assert '[model]\nname = "gpt-example"' in updated
    assert '[mcp_servers.other]\ncommand = "other"' in updated
    assert "[features]\nfoo = true" in updated
    assert 'command = "old"' not in updated
    assert 'OLD = "1"' not in updated
    assert updated.count("[mcp_servers.kicad]") == 1
    assert updated.count("[mcp_servers.kicad.env]") == 1
    assert 'KICAD_MCP_PROJECT_DIR = "/workspace/board"' in updated


def test_invalid_existing_json_fails_closed_without_modifying_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    original = b'{"mcpServers": invalid}\n'
    path.write_bytes(original)
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)
    generated, _ = generate_config("cursor", "/workspace/board", "readonly")

    message, ok = write_config("cursor", generated, "project")

    assert ok is False
    assert "invalid" in message.lower() or "json" in message.lower()
    assert path.read_bytes() == original
    assert list(tmp_path.glob("*.kicad-mcp.bak")) == []


def test_claude_code_write_uses_reversible_file_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".mcp.json"
    original = {"mcpServers": {"other": {"command": "other-tool"}}, "theme": "dark"}
    path.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)
    monkeypatch.setattr("kicad_mcp.setup.shutil.which", lambda _: None)

    result = setup_agent(
        "claude-code",
        project_dir="/workspace/project",
        mode="readonly",
        write=True,
        scope="project",
    )

    assert "Config written" in result
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["theme"] == "dark"
    assert "other" in updated["mcpServers"]
    assert updated["mcpServers"]["kicad"]["command"] == "uvx"
    backups = list(path.parent.glob(f"{path.name}.*.kicad-mcp.bak"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == original


def test_atomic_replace_failure_keeps_original_and_cleans_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    original = b'{"theme":"dark","mcpServers":{"other":{"command":"safe"}}}\n'
    path.write_bytes(original)
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)
    generated, _ = generate_config("cursor", "/workspace/board", "readonly")

    def fail_replace(_src: object, _dst: object) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr("kicad_mcp.setup.os.replace", fail_replace)
    message, ok = write_config("cursor", generated, "project")

    assert ok is False
    assert "replace failed" in message
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".mcp.json.*.tmp")) == []
