"""Verify the public read-only plugin package without contacting a provider."""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "integrations/cloud-directory-plugin"
URL = "https://kicad-mcp-pro.oaslananka.dev/mcp"


def _json(name: str) -> dict:
    return json.loads((PACKAGE / name).read_text(encoding="utf-8"))


def test_portable_openai_package_is_remote_and_separate_from_local_stdio() -> None:
    plugin = _json("plugin.json")
    remote = _json("mcp.json")
    local = json.loads((ROOT / "mcp.json").read_text())
    assert plugin["$schema"] == "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
    assert plugin["name"] == "kicad-cloud-review"
    assert plugin["license"] == "MIT"
    assert remote["$schema"] == "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
    assert remote["mcpServers"]["kicad-cloud"]["type"] == "streamable-http"
    assert remote["mcpServers"]["kicad-cloud"]["url"] == URL
    assert local["mcpServers"]["kicad"]["type"] == "stdio"


def test_openai_plugin_has_readonly_display_and_no_hooks_or_app_references() -> None:
    extension = _json("plugin.json")["extensions"]["com.openai"]
    info = extension["interface"]
    assert info["capabilities"] == ["Read"]
    assert info["privacyPolicyURL"] == "https://oaslananka.github.io/kicad-mcp-pro/privacy/"
    assert extension["onboardingSkill"] == "./skills/cloud-project-review/SKILL.md"
    assert (PACKAGE / extension["onboardingSkill"]).is_file()
    assert "apps" not in extension and "hooks" not in extension
    assert not (PACKAGE / ".app.json").exists()
    assert not (PACKAGE / "hooks").exists()


def test_openai_oauth_uses_cimd_and_only_read_scope_no_embedded_secrets() -> None:
    server = _json("mcp.json")["mcpServers"]["kicad-cloud"]
    assert server["extensions"]["com.openai"]["auth"] == {
        "type": "oauth",
        "client": {"mode": "cimd"},
        "resource": URL,
        "baseScopes": ["projects:read"],
    }
    assert not re.search(
        r'"(clientSecret|apiKey|authorizationUrl|tokenUrl)"',
        (PACKAGE / "mcp.json").read_text(encoding="utf-8"),
    )


def test_claude_plugin_points_to_the_same_public_https_service() -> None:
    claude = _json(".claude-plugin/plugin.json")
    assert claude["name"] == "kicad-cloud-review"
    assert claude["mcpServers"] == "./.mcp.json"
    assert claude["skills"] == ["./skills/cloud-project-review"]
    assert _json(".mcp.json") == {"mcpServers": {"kicad-cloud": {"type": "http", "url": URL}}}


def test_skill_uses_only_current_cloud_readonly_tool_catalog() -> None:
    text = (PACKAGE / "skills/cloud-project-review/SKILL.md").read_text()
    assert text.startswith("---\n")
    fields = yaml.safe_load(text.split("---", 2)[1])
    assert fields["name"] == "cloud-project-review"
    assert "without editing" in fields["description"]
    catalog = set(
        re.findall(
            r'mcp\.registerTool\("([a-z_]+)"',
            (ROOT / "apps/cloud/src/mcp.ts").read_text(),
        )
    )
    skill_tools = {
        "get_service_status",
        "list_projects",
        "list_devices",
        "get_project",
        "discover_project_workflow",
        "get_project_presence",
        "get_project_drc_counts",
        "get_project_engine_status",
        "get_project_board_counts",
        "get_project_schematic_counts",
    }
    assert skill_tools <= catalog
    assert all(name in text for name in skill_tools)
    assert "no write/export tools" in text
    assert "never infer" in text.lower()
