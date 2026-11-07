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
    assert "{ this is not valid json : [" == target.read_text(encoding="utf-8")


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
