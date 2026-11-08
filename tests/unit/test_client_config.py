"""Tests for guided, safe, and reversible local AI client configuration."""

import json

import pytest

from kicad_mcp.services.client_config import (
    ClientConfigError,
    get_owned_client_configs,
    remove_client_config_entry,
    write_client_config_safe,
)


def test_write_client_config_new_file(tmp_path) -> None:
    target = tmp_path / "claude_desktop_config.json"
    snippet = {
        "mcpServers": {
            "kicad-mcp-pro": {
                "command": "uvx",
                "args": ["kicad-mcp-pro@4.8.1"],
            }
        }
    }
    result = write_client_config_safe(
        client="claude-desktop",
        config_path=target,
        snippet=snippet,
        registry_root=tmp_path / "registry",
    )
    assert result.success is True
    assert target.exists()

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "kicad-mcp-pro" in data["mcpServers"]
    assert data["mcpServers"]["kicad-mcp-pro"]["command"] == "uvx"

    # Verify ownership tracked
    owned = get_owned_client_configs(registry_root=tmp_path / "registry")
    assert "claude-desktop" in owned
    assert str(target.resolve()) in owned["claude-desktop"]


def test_write_client_config_preserves_other_servers(tmp_path) -> None:
    target = tmp_path / "config.json"
    existing_content = {
        "mcpServers": {
            "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
            "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"]},
        },
        "preferences": {"theme": "dark"},
    }
    target.write_text(json.dumps(existing_content, indent=2), encoding="utf-8")

    snippet = {"mcpServers": {"kicad-mcp-pro": {"command": "uvx", "args": ["kicad-mcp-pro@4.8.1"]}}}
    result = write_client_config_safe(
        client="claude-desktop",
        config_path=target,
        snippet=snippet,
        registry_root=tmp_path / "registry",
    )
    assert result.success is True

    # Backup was created
    bak = target.with_suffix(".json.bak")
    assert bak.exists()
    assert "sqlite" in bak.read_text(encoding="utf-8")
    assert "kicad-mcp-pro" not in bak.read_text(encoding="utf-8")

    # Target has both existing and new server
    merged = json.loads(target.read_text(encoding="utf-8"))
    assert "sqlite" in merged["mcpServers"]
    assert "github" in merged["mcpServers"]
    assert "kicad-mcp-pro" in merged["mcpServers"]
    assert merged["preferences"]["theme"] == "dark"


def test_write_client_config_rejects_malformed_existing(tmp_path) -> None:
    target = tmp_path / "broken.json"
    target.write_text("{ this is not valid json : [", encoding="utf-8")

    snippet = {"mcpServers": {"kicad-mcp-pro": {"command": "uvx"}}}
    with pytest.raises(ClientConfigError) as exc_info:
        write_client_config_safe(
            client="claude-desktop",
            config_path=target,
            snippet=snippet,
            registry_root=tmp_path / "registry",
        )
    assert "malformed" in str(exc_info.value).lower()
    # Broken file was not overwritten
    assert target.read_text(encoding="utf-8") == "{ this is not valid json : ["


def test_remove_owned_client_config_entry_preserves_other_servers(tmp_path) -> None:
    target = tmp_path / "config.json"
    initial_content = {
        "mcpServers": {
            "sqlite": {"command": "uvx", "args": ["mcp-server-sqlite"]},
            "kicad-mcp-pro": {"command": "uvx", "args": ["kicad-mcp-pro@4.8.1"]},
        }
    }
    target.write_text(json.dumps(initial_content), encoding="utf-8")

    reg = tmp_path / "registry"
    write_client_config_safe(
        "cursor", target, {"mcpServers": {"kicad-mcp-pro": {}}}, registry_root=reg
    )

    # Now remove entry
    removed = remove_client_config_entry("cursor", target, registry_root=reg)
    assert removed is True

    data = json.loads(target.read_text(encoding="utf-8"))
    assert "kicad-mcp-pro" not in data.get("mcpServers", {})
    assert "sqlite" in data["mcpServers"]


def test_user_modified_owned_entry_is_preserved_during_uninstall(tmp_path) -> None:
    target = tmp_path / "client.json"
    reg = tmp_path / "registry"
    write_client_config_safe(
        "claude",
        target,
        {"mcpServers": {"kicad-mcp-pro": {"command": "uv", "args": ["tool", "run"]}}},
        registry_root=reg,
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    data["mcpServers"]["kicad-mcp-pro"]["args"].append("--user-customization")
    data["mcpServers"]["sqlite"] = {"command": "other"}
    target.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ClientConfigError, match="changed"):
        remove_client_config_entry("claude", target, registry_root=reg)
    assert json.loads(target.read_text(encoding="utf-8")) == data


def test_legacy_path_only_ownership_does_not_authorize_deletion(tmp_path) -> None:
    target = tmp_path / "config.json"
    target.write_text(
        json.dumps({"mcpServers": {"kicad-mcp-pro": {"command": "custom"}}}),
        encoding="utf-8",
    )
    registry = tmp_path / "registry"
    registry.mkdir()
    (registry / "owned_client_configs.json").write_text(
        json.dumps({"claude": [str(target.resolve())]}),
        encoding="utf-8",
    )
    with pytest.raises(ClientConfigError, match="unverified"):
        remove_client_config_entry("claude", target, registry_root=registry)
    assert target.exists()


def test_vscode_server_entry_merge_and_scoped_removal(tmp_path) -> None:
    target = tmp_path / "settings.json"
    registry = tmp_path / "registry"
    target.write_text(
        json.dumps({"servers": {"other": {"type": "stdio", "command": "npx"}}}),
        encoding="utf-8",
    )
    write_client_config_safe(
        "vscode",
        target,
        {"servers": {"kicad-mcp-pro": {"type": "stdio", "command": "uvx"}}},
        registry_root=registry,
    )
    data = json.loads(target.read_text(encoding="utf-8"))
    assert set(data["servers"]) == {"other", "kicad-mcp-pro"}
    assert remove_client_config_entry("vscode", target, registry_root=registry)
    data = json.loads(target.read_text(encoding="utf-8"))
    assert list(data["servers"]) == ["other"]
