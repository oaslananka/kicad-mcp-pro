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


@pytest.mark.parametrize(
    ("existing", "generated", "message"),
    [
        ("[]", '{"mcpServers": {"kicad": {}}}', "must be an object"),
        ("{}", "{}", "missing object key"),
        ('{"mcpServers": []}', '{"mcpServers": {"kicad": {}}}', "must be an object"),
    ],
)
def test_json_merge_rejects_unsafe_shapes(existing: str, generated: str, message: str) -> None:
    from kicad_mcp.setup import ConfigValidationError, _merge_json_config

    with pytest.raises(ConfigValidationError, match=message):
        _merge_json_config(existing, generated, "cursor")


def test_codex_toml_merge_rejects_invalid_and_conflicting_input() -> None:
    from kicad_mcp.setup import ConfigValidationError, _merge_codex_toml

    generated = '[mcp_servers.kicad]\ncommand = "uvx"\nargs = []\n'
    with pytest.raises(ConfigValidationError, match="Invalid TOML"):
        _merge_codex_toml("[broken", generated)

    with pytest.raises(ConfigValidationError, match="Merged TOML"):
        _merge_codex_toml('mcp_servers = "occupied"\n', generated)


def test_toml_array_header_is_not_treated_as_owned_table() -> None:
    from kicad_mcp.setup import _toml_section_header

    assert _toml_section_header("[[plugins]]") is None


def test_merged_config_rejects_unsupported_writable_format() -> None:
    from kicad_mcp.setup import ConfigValidationError, _merged_config

    with pytest.raises(ConfigValidationError, match="Unsupported writable config format"):
        _merged_config("", "", "cursor", "toml")


def test_atomic_write_closes_descriptor_when_pre_write_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from kicad_mcp import setup as setup_module

    path = tmp_path / "mcp.json"
    original = '{"theme":"dark"}\n'
    path.write_text(original, encoding="utf-8")
    closed: list[int] = []
    real_close = os.close

    def track_close(fd: int) -> None:
        closed.append(fd)
        real_close(fd)

    def fail_chmod(*_args: object, **_kwargs: object) -> None:
        raise OSError("chmod failed")

    monkeypatch.setattr(setup_module.os, "close", track_close)
    monkeypatch.setattr(setup_module.os, "chmod", fail_chmod)

    with pytest.raises(OSError, match="chmod failed"):
        setup_module._atomic_write_text(path, '{"theme":"light"}\n')

    assert closed
    assert path.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".mcp.json.*.tmp")) == []


def test_write_config_rejects_generated_config_that_fails_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mcp.json"
    monkeypatch.setattr("kicad_mcp.setup.resolve_path", lambda *_: path)

    message, ok = write_config("cursor", '{"mcpServers": {}}', "project")

    assert ok is False
    assert "mcpServers.kicad" in message
    assert path.exists() is False


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


def test_setup_agent_write_targets_explicit_project_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.setup import setup_agent

    project = tmp_path / "project"
    cwd = tmp_path / "cwd"
    project.mkdir()
    cwd.mkdir()
    monkeypatch.chdir(cwd)

    result = setup_agent("cursor", project_dir=str(project), write=True, scope="project")

    target = project / ".cursor" / "mcp.json"
    assert "Config written" in result
    assert target.exists()
    assert not (cwd / ".cursor" / "mcp.json").exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["mcpServers"]["kicad"]["env"]["KICAD_MCP_PROJECT_DIR"] == str(project)


def test_project_backup_restore_honors_explicit_project_dir(tmp_path: Path) -> None:
    from kicad_mcp.setup import restore_config, setup_agent

    project = tmp_path / "project"
    target = project / ".cursor" / "mcp.json"
    target.parent.mkdir(parents=True)
    original = {"theme": "dark", "mcpServers": {"other": {"command": "safe"}}}
    target.write_text(json.dumps(original, indent=2) + "\n", encoding="utf-8")

    setup_agent("cursor", project_dir=str(project), write=True, scope="project")
    restored = restore_config("cursor", "project", project_dir=str(project))

    assert "Restored" in restored
    assert json.loads(target.read_text(encoding="utf-8")) == original
