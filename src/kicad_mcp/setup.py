"""KiCad MCP setup wizard, config generator, backup/restore, and validation.

Phase 2 deliverables:
- Agent-specific config generators (JSON, TOML)
- Platform-aware path resolution (Windows/macOS/Linux)
- Project/user/global scope support
- Backup and restore of existing configs
- Config validation per agent format
- Interactive wizard (``kicad-mcp-pro setup --wizard``)
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Scope = Literal["project", "user", "global"]
"""Where to write the config file."""

ConfigFormat = Literal["json", "toml"]
"""Config file format for the agent."""

AgentKind = Literal["local", "remote"]
"""Whether the agent runs locally or requires a remote server."""

# ---------------------------------------------------------------------------
# Agent metadata
# ---------------------------------------------------------------------------


@dataclass
class AgentInfo:
    """Describes one supported MCP host."""

    key: str
    """Short key used in CLI commands (e.g. ``claude-code``)."""
    display: str
    """Human-readable name."""
    kind: AgentKind
    """Local stdio or remote HTTP agent."""
    format: ConfigFormat
    """Config file format."""
    supports_scope: list[Scope]
    """Which scopes this agent supports."""
    doc_url: str = ""
    """Link to agent documentation."""


AGENTS: dict[str, AgentInfo] = {
    "claude-code": AgentInfo(
        key="claude-code",
        display="Claude Code (claude.ai/code)",
        kind="local",
        format="json",
        supports_scope=["project", "user"],
        doc_url="docs/agents/claude-code.md",
    ),
    "codex": AgentInfo(
        key="codex",
        display="Codex CLI (github.com/openai/codex)",
        kind="local",
        format="toml",
        supports_scope=["user"],
        doc_url="docs/agents/codex.md",
    ),
    "gemini": AgentInfo(
        key="gemini",
        display="Gemini CLI (cloud.google.com/gemini-cli)",
        kind="local",
        format="json",
        supports_scope=["user"],
        doc_url="docs/agents/gemini-cli.md",
    ),
    "opencode": AgentInfo(
        key="opencode",
        display="OpenCode (opencode.ai)",
        kind="local",
        format="json",
        supports_scope=["project", "user"],
        doc_url="docs/agents/opencode.md",
    ),
    "cursor": AgentInfo(
        key="cursor",
        display="Cursor (cursor.sh)",
        kind="local",
        format="json",
        supports_scope=["project", "user"],
        doc_url="docs/agents/cursor.md",
    ),
    "vscode": AgentInfo(
        key="vscode",
        display="VS Code / GitHub Copilot",
        kind="local",
        format="json",
        supports_scope=["project"],
        doc_url="docs/agents/vscode-copilot.md",
    ),
    "claude-desktop": AgentInfo(
        key="claude-desktop",
        display="Claude Desktop",
        kind="local",
        format="json",
        supports_scope=["user"],
        doc_url="docs/agents/claude-desktop.md",
    ),
    "antigravity": AgentInfo(
        key="antigravity",
        display="Google Antigravity IDE",
        kind="local",
        format="json",
        supports_scope=["user"],
        doc_url="docs/agents/antigravity.md",
    ),
    "chatgpt": AgentInfo(
        key="chatgpt",
        display="ChatGPT Web (remote app)",
        kind="remote",
        format="json",
        supports_scope=[],
        doc_url="docs/agents/chatgpt-app.md",
    ),
    "claude-ai": AgentInfo(
        key="claude-ai",
        display="Claude.ai Web (remote connector)",
        kind="remote",
        format="json",
        supports_scope=[],
        doc_url="docs/agents/claude-ai.md",
    ),
}

# ---------------------------------------------------------------------------
# Platform-aware config paths
# ---------------------------------------------------------------------------

_CONFIG_PATHS: dict[str, dict[Scope, str]] = {
    # ── Claude Code ──
    "claude-code": {
        "project": ".mcp.json",
        "user": "~/.claude.json",
    },
    # ── Codex ──
    "codex": {
        "user": "~/.codex/config.toml",
    },
    # ── Gemini CLI ──
    "gemini": {
        "user": "~/.gemini/settings.json",
    },
    # ── OpenCode ──
    "opencode": {
        "project": "opencode.json",
        "user": "~/.config/opencode/opencode.json",
    },
    # ── Cursor ──
    "cursor": {
        "project": ".cursor/mcp.json",
        "user": "~/.cursor/mcp.json",
    },
    # ── VS Code ──
    "vscode": {
        "project": ".vscode/mcp.json",
    },
    # ── Claude Desktop (platform-specific at runtime) ──
    "claude-desktop": {
        "user": "",  # resolved dynamically in resolve_path()
    },
    # ── Antigravity ──
    "antigravity": {
        "user": "~/.gemini/config/mcp_config.json",
    },
}


def _claude_desktop_path() -> Path:
    """Return the platform-appropriate Claude Desktop config path."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Claude"
            / "claude_desktop_config.json"
        )
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def resolve_path(agent_key: str, scope: str, project_dir: str | Path | None = None) -> Path:
    """Resolve the config file path for an agent and scope.

    Respects platform (Windows/macOS/Linux) differences.
    """
    info = AGENTS.get(agent_key)
    if info is None:
        msg = f"Unknown agent: {agent_key}"
        raise ValueError(msg)
    if scope not in info.supports_scope:
        valid = ", ".join(info.supports_scope)
        msg = f"Agent '{agent_key}' does not support scope '{scope}'. Valid: {valid}"
        raise ValueError(msg)

    if agent_key == "claude-desktop":
        return _claude_desktop_path()

    entry = _CONFIG_PATHS.get(agent_key, {}).get(scope)
    if entry is None:
        msg = f"No path defined for {agent_key}/{scope}"
        raise ValueError(msg)

    raw = entry
    # On Windows, rewrite Unix-style paths
    if sys.platform == "win32":
        raw = raw.replace("~", os.environ.get("USERPROFILE", "~"))
    path = Path(raw).expanduser()
    if scope == "project" and project_dir is not None and not path.is_absolute():
        path = Path(project_dir).expanduser() / path
    return path.resolve()


def resolve_all_paths(agent_key: str) -> dict[Scope, Path]:
    """Return all available config paths for an agent."""
    info = AGENTS.get(agent_key)
    if info is None:
        return {}
    result: dict[Scope, Path] = {}
    for scope in info.supports_scope:
        try:
            result[scope] = resolve_path(agent_key, scope)
        except ValueError:
            pass
    return result


# ---------------------------------------------------------------------------
# Environment variable defaults
# ---------------------------------------------------------------------------

_READONLY_ENV: dict[str, str] = {
    "KICAD_MCP_PROJECT_DIR": "{project_dir}",
    "KICAD_MCP_PROFILE": "default",
    "KICAD_MCP_OPERATING_MODE": "readonly",
}

_WRITE_ENV: dict[str, str] = {
    "KICAD_MCP_PROJECT_DIR": "{project_dir}",
    "KICAD_MCP_PROFILE": "build",
    "KICAD_MCP_OPERATING_MODE": "write",
}

_MANUFACTURING_ENV: dict[str, str] = {
    "KICAD_MCP_PROJECT_DIR": "{project_dir}",
    "KICAD_MCP_PROFILE": "release",
    "KICAD_MCP_OPERATING_MODE": "manufacturing",
}


def _env_for_mode(mode: str, project_dir: str) -> dict[str, str]:
    env_map = {
        "readonly": _READONLY_ENV,
        "write": _WRITE_ENV,
        "manufacturing": _MANUFACTURING_ENV,
    }
    env = dict(env_map.get(mode, _READONLY_ENV))
    return {k: v.format(project_dir=project_dir) for k, v in env.items()}


# ---------------------------------------------------------------------------
# Config generators
# ---------------------------------------------------------------------------


def generate_config(
    agent_key: str,
    project_dir: str,
    mode: str = "readonly",
    *,
    transport: str = "stdio",
    url: str = "",
) -> tuple[str, ConfigFormat]:
    """Generate a configuration snippet for the specified agent.

    Returns ``(config_string, format)``.
    """
    info = AGENTS.get(agent_key)
    if info is None:
        msg = f"Unsupported agent: {agent_key}"
        raise ValueError(msg)

    if info.kind == "remote":
        return _generate_remote_config(agent_key, url), info.format

    return _generate_local_config(agent_key, project_dir, mode, transport), info.format


def _make_stdio_server(command: str, args: list[str], env: dict[str, str]) -> dict[str, object]:
    """Build a stdio server dict."""
    return {"command": command, "args": args, "env": env}


def _make_mcp_servers_block(
    server: dict[str, object],
    server_id: str = "kicad",
    server_type: str | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    """Build an mcpServers block with optional type field."""
    entry = dict(server)
    if server_type:
        entry["type"] = server_type
    return {"mcpServers": {server_id: entry}}


def _generate_local_config(
    agent_key: str,
    project_dir: str,
    mode: str = "readonly",
    transport: str = "stdio",
) -> str:
    """Generate a local stdio/http config for a local agent."""
    env = _env_for_mode(mode, project_dir)

    if transport == "http":
        url = os.environ.get("KICAD_MCP_URL", "http://127.0.0.1:8765/mcp")
        return _generate_http_config(agent_key, url, env)

    stdio_cmd = "uvx"
    stdio_args = ["kicad-mcp-pro"]
    server = _make_stdio_server(stdio_cmd, stdio_args, env)

    configs: dict[str, str] = {
        "claude-code": json.dumps(_make_mcp_servers_block({**server, "type": "stdio"}), indent=2),
        "gemini": json.dumps(_make_mcp_servers_block({**server, "trust": False}), indent=2),
        "cursor": json.dumps(_make_mcp_servers_block(server), indent=2),
        "claude-desktop": json.dumps(_make_mcp_servers_block(server), indent=2),
        "antigravity": json.dumps(_make_mcp_servers_block(server), indent=2),
    }

    if agent_key in configs:
        return configs[agent_key]

    if agent_key == "opencode":
        return json.dumps(
            {
                "mcp": {
                    "kicad": {
                        "type": "local",
                        "command": stdio_cmd,
                        "args": list(stdio_args),
                        "enabled": True,
                        "environment": env,
                    }
                }
            },
            indent=2,
        )

    if agent_key == "vscode":
        vscode_env = {
            k: ("${workspaceFolder}" if k == "KICAD_MCP_PROJECT_DIR" else v) for k, v in env.items()
        }
        return json.dumps(
            {
                "servers": {
                    "kicad": {
                        "type": "stdio",
                        "command": stdio_cmd,
                        "args": stdio_args,
                        "cwd": "${workspaceFolder}",
                        "env": vscode_env,
                    }
                }
            },
            indent=2,
        )

    if agent_key == "codex":
        return _generate_codex_toml(project_dir, mode)

    return json.dumps(_make_mcp_servers_block(server), indent=2)


def _generate_http_config(agent_key: str, url: str, env: dict[str, str]) -> str:
    """Generate an HTTP transport config snippet."""
    if agent_key == "vscode":
        return json.dumps(
            {
                "servers": {
                    "kicadCloud": {
                        "type": "http",
                        "url": url,
                        "headers": {"Authorization": "Bearer ${input:kicad-token}"},
                    }
                }
            },
            indent=2,
        )
    if agent_key == "opencode":
        return json.dumps(
            {
                "mcp": {
                    "kicad-cloud": {
                        "type": "remote",
                        "url": url,
                        "enabled": True,
                    }
                }
            },
            indent=2,
        )
    return json.dumps(
        {"mcpServers": {"kicad": {"type": "http", "url": url, "env": env}}},
        indent=2,
    )


def _generate_remote_config(agent_key: str, url: str) -> str:
    """Generate a remote-only config snippet (chatgpt, claude-ai)."""
    docs_path = "docs/agents/"
    remote_docs = {
        "chatgpt": ("ChatGPT Web App", "chatgpt-app.md"),
        "claude-ai": ("Claude.ai Custom Connector", "claude-ai.md"),
    }
    if not url:
        url = "https://mcp.kicad.example.com/mcp"
    entry = remote_docs.get(agent_key)
    if entry:
        name, doc_file = entry
        return f"# {name}\n# URL: {url}\n# See {docs_path}{doc_file} for setup instructions."
    return f"# Remote MCP endpoint\n# URL: {url}"


def _generate_codex_toml(project_dir: str, mode: str) -> str:
    """Generate Codex TOML config fragment."""
    profile = "analysis"
    operating_mode = mode
    lines = [
        "[mcp_servers.kicad]",
        "enabled = true",
        'command = "uvx"',
        'args = ["kicad-mcp-pro"]',
        'cwd = "."',
        "startup_timeout_sec = 20",
        "tool_timeout_sec = 120",
        'default_tools_approval_mode = "prompt"',
        "",
        "[mcp_servers.kicad.env]",
        f'KICAD_MCP_PROJECT_DIR = "{project_dir}"',
        f'KICAD_MCP_PROFILE = "{profile}"',
        f'KICAD_MCP_OPERATING_MODE = "{operating_mode}"',
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------

_BACKUP_SUFFIX = ".kicad-mcp.bak"


def backup_config(path: Path) -> Path | None:
    """Back up an existing config file. Returns backup path, or None if no file existed."""
    if not path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = path.with_suffix(f"{path.suffix}.{timestamp}{_BACKUP_SUFFIX}")
    shutil.copy2(path, bak)
    return bak


def list_backups(
    agent_key: str, scope: str, *, project_dir: str | Path | None = None
) -> list[Path]:
    """List all backup files for a given agent config."""
    try:
        path = (
            resolve_path(agent_key, str(scope), project_dir)
            if project_dir is not None
            else resolve_path(agent_key, str(scope))
        )
    except ValueError:
        return []
    parent = path.parent
    if not parent.exists():
        return []
    pattern = f"{path.name}.*{_BACKUP_SUFFIX}"
    return sorted(parent.glob(pattern), reverse=True)


def restore_backup(agent_key: str, scope: str, *, project_dir: str | Path | None = None) -> str:
    """Restore the most recent backup for an agent config."""
    backups = list_backups(agent_key, scope, project_dir=project_dir)
    if not backups:
        return f"No backups found for {agent_key} ({scope})."
    latest = backups[0]
    try:
        path = (
            resolve_path(agent_key, scope, project_dir)
            if project_dir is not None
            else resolve_path(agent_key, scope)
        )
        shutil.copy2(latest, path)
        return f"Restored {path} from {latest}"
    except (OSError, ValueError) as exc:
        return f"Restore failed: {exc}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class ConfigValidationError(ValueError):
    """Raised when a config fails validation."""


def validate_config(config_str: str, agent_key: str, fmt: ConfigFormat) -> list[str]:
    """Validate a configuration string for a specific agent.

    Returns a list of issues (empty = valid).
    """
    issues: list[str] = []

    if not config_str.strip():
        return ["Config string is empty."]

    if fmt == "json":
        try:
            data = json.loads(config_str)
        except json.JSONDecodeError as exc:
            return [f"Invalid JSON: {exc}"]

        if agent_key == "codex":
            # TOML is validated via the Codex-specific path below
            pass
        elif agent_key == "vscode":
            if "servers" not in data:
                issues.append('Missing top-level "servers" key (expected for VS Code).')
            elif "kicad" not in data.get("servers", {}):
                issues.append('Missing "servers.kicad" entry.')
        elif agent_key == "opencode":
            if "mcp" not in data:
                issues.append('Missing top-level "mcp" key (expected for OpenCode).')
            elif "kicad" not in data.get("mcp", {}):
                # Could be remote with a different key name
                pass
        else:
            if "mcpServers" not in data:
                issues.append('Missing top-level "mcpServers" key.')
            elif "kicad" not in data.get("mcpServers", {}):
                issues.append('Missing "mcpServers.kicad" entry.')

    elif fmt == "toml":
        if "command" not in config_str or "args" not in config_str:
            issues.append("TOML config should contain command and args keys.")
        if "[mcp_servers.kicad]" not in config_str:
            issues.append("Missing [mcp_servers.kicad] section header (expected for Codex).")

    return issues


# ---------------------------------------------------------------------------
# Write config
# ---------------------------------------------------------------------------


WriteResult = tuple[str, bool]
"""``(path_or_message, success)``"""


_JSON_CONFIG_ROOTS: dict[str, str] = {
    "vscode": "servers",
    "opencode": "mcp",
}


def _merge_json_config(existing: str, generated: str, agent_key: str) -> str:
    """Merge only the generated MCP server entries into an existing JSON config."""
    try:
        current = json.loads(existing) if existing.strip() else {}
        desired = json.loads(generated)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON configuration: {exc}"
        raise ConfigValidationError(msg) from exc
    if not isinstance(current, dict) or not isinstance(desired, dict):
        raise ConfigValidationError("JSON client configuration must be an object.")

    root_key = _JSON_CONFIG_ROOTS.get(agent_key, "mcpServers")
    desired_servers = desired.get(root_key)
    if not isinstance(desired_servers, dict):
        raise ConfigValidationError(f'Generated config is missing object key "{root_key}".')

    merged = dict(current)
    current_servers = merged.get(root_key, {})
    if not isinstance(current_servers, dict):
        raise ConfigValidationError(f'Existing key "{root_key}" must be an object.')
    merged_servers = dict(current_servers)
    merged_servers.update(desired_servers)
    merged[root_key] = merged_servers
    return json.dumps(merged, indent=2, ensure_ascii=False) + "\n"


def _toml_section_header(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    if stripped.startswith("[["):
        return None
    return stripped[1:-1].strip()


def _merge_codex_toml(existing: str, generated: str) -> str:
    """Replace only the kicad MCP tables while preserving unrelated TOML text."""
    try:
        if existing.strip():
            tomllib.loads(existing)
        tomllib.loads(generated)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Invalid TOML configuration: {exc}"
        raise ConfigValidationError(msg) from exc

    kept: list[str] = []
    skipping_owned = False
    for line in existing.splitlines(keepends=True):
        header = _toml_section_header(line)
        if header is not None:
            skipping_owned = header == "mcp_servers.kicad" or header.startswith(
                "mcp_servers.kicad."
            )
        if not skipping_owned:
            kept.append(line)

    prefix = "".join(kept).rstrip()
    merged = f"{prefix}\n\n{generated.strip()}\n" if prefix else f"{generated.strip()}\n"
    try:
        tomllib.loads(merged)
    except tomllib.TOMLDecodeError as exc:
        msg = f"Merged TOML configuration is invalid: {exc}"
        raise ConfigValidationError(msg) from exc
    return merged


def _merged_config(existing: str, generated: str, agent_key: str, fmt: ConfigFormat) -> str:
    if fmt == "json":
        return _merge_json_config(existing, generated, agent_key)
    if agent_key == "codex" and fmt == "toml":
        return _merge_codex_toml(existing, generated)
    raise ConfigValidationError(f"Unsupported writable config format: {fmt}")


def _atomic_write_text(path: Path, content: str) -> None:
    """Atomically replace one local config file using a same-directory temporary file."""
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        if path.exists():
            os.chmod(temp_path, path.stat().st_mode)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if fd >= 0:
            os.close(fd)
        temp_path.unlink(missing_ok=True)


def write_config(
    agent_key: str,
    config_str: str,
    scope: str = "project",
    *,
    backup: bool = True,
    project_dir: str | Path | None = None,
) -> WriteResult:
    """Merge and atomically write one client config. Returns ``(path, success)``."""
    info = AGENTS.get(agent_key)
    if info is None:
        return f"Unknown agent: {agent_key}", False
    if info.kind == "remote":
        return f"Agent '{agent_key}' is remote-only. No local config to write.", False
    if scope not in info.supports_scope:
        valid = ", ".join(info.supports_scope)
        return f"Agent '{agent_key}' does not support scope '{scope}'. Valid: {valid}", False

    try:
        path = (
            resolve_path(agent_key, scope, project_dir)
            if project_dir is not None
            else resolve_path(agent_key, scope)
        )
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        merged = _merged_config(existing, config_str, agent_key, info.format)
        issues = validate_config(merged, agent_key, info.format)
        if issues:
            raise ConfigValidationError("; ".join(issues))
        path.parent.mkdir(parents=True, exist_ok=True)
        if backup and path.exists():
            backup_config(path)
        _atomic_write_text(path, merged)
    except (OSError, ConfigValidationError, UnicodeError) as exc:
        return f"Config write failed: {exc}", False
    return str(path), True


# ---------------------------------------------------------------------------
# Doctor integration — check agent configs
# ---------------------------------------------------------------------------


AgentConfigEntry = dict[str, object]
"""A single agent config check result entry."""


def check_agent_config(agent_key: str) -> dict[str, object]:
    """Check if an agent has a valid kicad-mcp config file.

    Returns a dict with keys: key, config_path, exists, valid, issues.
    """
    info = AGENTS.get(agent_key)
    if info is None or info.kind == "remote":
        return {"key": agent_key, "found": False, "note": "remote-only"}

    result: dict[str, object] = {"key": agent_key, "configs": {}}
    configs: dict[str, AgentConfigEntry] = {}
    for scope in info.supports_scope:
        try:
            path = resolve_path(agent_key, scope)
        except ValueError:
            continue

        entry: AgentConfigEntry = {"path": str(path), "exists": False}
        if path.exists():
            entry["exists"] = True
            try:
                text = path.read_text(encoding="utf-8")
                issues = validate_config(text, agent_key, info.format)
                entry["valid"] = len(issues) == 0
                if issues:
                    entry["issues"] = list(issues)
            except Exception as exc:
                entry["valid"] = False
                entry["issues"] = [str(exc)]
        configs[scope] = entry

    result["configs"] = configs
    return result


def check_all_agent_configs() -> list[dict[str, object]]:
    """Run config checks for all local agents."""
    return [check_agent_config(key) for key, info in AGENTS.items() if info.kind == "local"]


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


def _ask(question: str, default: str = "") -> str:
    """Prompt user for input (CLI fallback)."""
    prompt = f"{question} "
    if default:
        prompt += f"[{default}] "
    try:
        value = input(prompt).strip()
        return value or default
    except (EOFError, KeyboardInterrupt):
        return default


def _choose(label: str, options: list[str], default: str = "") -> str:
    """Let user choose from a list."""
    print(f"\n{label}")
    for i, opt in enumerate(options, 1):
        marker = " [default]" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    while True:
        default_num = str(options.index(default) + 1) if default else "1"
        raw = _ask(f"Enter number (1-{len(options)})", default=default_num)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            pass
        print(f"Invalid choice. Enter 1-{len(options)}.")


def run_wizard() -> str:
    """Interactive setup wizard.

    Returns a human-readable summary of what was done.
    """
    lines: list[str] = [
        "╔══════════════════════════════════════════╗",
        "║        KiCad MCP Setup Wizard            ║",
        "╚══════════════════════════════════════════╝",
        "",
    ]

    # 1. Choose agent
    local_agents = [(k, v) for k, v in AGENTS.items() if v.kind == "local"]
    agent_choices = [f"{info.display} ({key})" for key, info in local_agents]
    default_agent_key = "claude-code"
    default_info = AGENTS[default_agent_key]
    default_choice = f"{default_info.display} ({default_agent_key})"
    chosen = _choose("Which agent do you want to configure?", agent_choices, default=default_choice)
    agent_key = chosen.split("(")[-1].rstrip(")")
    info = AGENTS[agent_key]
    lines.append(f"Agent: {info.display}")

    # 2. Project dir
    default_dir = os.environ.get("KICAD_MCP_PROJECT_DIR", os.getcwd())
    project_dir = _ask("KiCad project directory (absolute path)", default_dir)
    lines.append(f"Project directory: {project_dir}")

    # 3. Mode
    mode = _choose("Operating mode?", ["readonly", "write", "manufacturing"], "readonly")
    lines.append(f"Mode: {mode}")

    # 4. Scope
    if len(info.supports_scope) > 1:
        scope = _choose("Config scope?", list(info.supports_scope), "project")
    elif info.supports_scope:
        scope = info.supports_scope[0]
    else:
        scope = "project"
    lines.append(f"Scope: {scope}")

    # 5. Backup
    backup_choice = _ask("Back up existing config if present?", "yes")
    do_backup = backup_choice.lower().startswith("y")

    # 6. Generate
    config_str, fmt = generate_config(agent_key, project_dir, mode)

    # Print config and ask
    print(f"\nGenerated config ({fmt}):")
    print("-" * 50)
    print(config_str)
    print("-" * 50)

    write_choice = _ask("Write this config to disk?", "yes")
    if write_choice.lower().startswith("y"):
        path_str, ok = write_config(agent_key, config_str, scope, backup=do_backup)
        if ok:
            lines.append(f"✓ Config written: {path_str}")
            # Run smoke test
            test_choice = _ask("Run connectivity test?", "yes")
            if test_choice.lower().startswith("y"):
                test_result = _run_smoke_test(agent_key)
                lines.append(test_result)
        else:
            lines.append(f"✗ Write failed: {path_str}")
    else:
        lines.append("Config not written (printed above).")

    lines.append("")
    lines.append("Setup complete!")

    # Show any extra notes
    if scope == "project":
        lines.append(f"Tip: Add '{Path(project_dir).resolve()}' to your agent's project workspace.")
    lines.append(f"See {info.doc_url} for more details.")

    return "\n".join(lines)


def _run_smoke_test(agent_key: str) -> str:
    """Run a quick connectivity test after writing config."""
    if agent_key == "claude-code":
        claude_path = shutil.which("claude")
        if claude_path:
            try:
                import subprocess

                result = subprocess.run(
                    [claude_path, "mcp", "list"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if "kicad" in result.stdout:
                    return "✓ Smoke test: 'claude mcp list' shows kicad server."
                return "⚠ Smoke test: 'claude mcp list' ran but kicad not found."
            except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
                return f"⚠ Smoke test skipped: {exc}"
    return "✓ Config written (smoke test not available for this agent)."


# ---------------------------------------------------------------------------
# Main entry points (called from server.py)
# ---------------------------------------------------------------------------


def setup_agent(
    agent: str,
    project_dir: str | None = None,
    mode: str = "readonly",
    write: bool = False,
    scope: str = "project",
    url: str = "",
    transport: str = "stdio",
) -> str:
    """Configure kicad-mcp for a specific agent.

    This is the main entry point from ``server.py setup`` command.
    """
    if agent not in AGENTS:
        agents_list = ", ".join(sorted(AGENTS))
        return f"Unsupported agent: {agent}\nSupported: {agents_list}"

    # Backward-compat: wizards
    if agent == "interactive":
        return run_wizard()

    info = AGENTS[agent]
    project = project_dir or os.environ.get("KICAD_MCP_PROJECT_DIR", os.getcwd())

    config_str, fmt = generate_config(agent, project, mode, transport=transport, url=url)

    if write:
        if info.kind == "remote":
            return (
                f"Agent '{agent}' is remote-only. No local config to write.\n\n"
                f"Setup instructions:\n{config_str}"
            )
        if scope not in info.supports_scope:
            valid = ", ".join(info.supports_scope)
            return (
                f"Agent '{agent}' does not support scope '{scope}'.\n"
                f"Valid scopes: {valid}\n\nConfig snippet:\n{config_str}"
            )

        path_str, ok = write_config(
            agent, config_str, scope, project_dir=project if scope == "project" else None
        )
        if ok:
            # Validate after writing
            issues = validate_config(config_str, agent, fmt)
            validation = ""
            if issues:
                validation = f"\n⚠ Config written but has {len(issues)} issue(s):"
                for iss in issues:
                    validation += f"\n  - {iss}"
            return f"✓ Config written to {path_str}{validation}\n\n{config_str}"
        return f"Failed to write config: {path_str}\n\nConfig snippet:\n{config_str}"

    # Preview mode: just print config
    return config_str


def _check_kicad_mcp_available() -> bool:
    """Check whether the kicad-mcp-pro executable is available on PATH."""
    import shutil

    return shutil.which("kicad-mcp-pro") is not None


def setup_wizard() -> str:
    """Fallback wizard for CLI-free environments."""
    lines = [
        "KiCad MCP Setup Wizard",
        "=" * 40,
        "",
        "Supported agents:",
    ]
    for key, info in sorted(AGENTS.items()):
        lines.append(f"  {key:20s} {info.display}")
    lines.append("")
    lines.append("Run: kicad-mcp-pro setup <agent-name>")
    lines.append("Example: kicad-mcp-pro setup claude-code")
    lines.append("")
    lines.append("For interactive mode: kicad-mcp-pro setup --wizard")
    return "\n".join(lines)


def restore_config(
    agent: str, scope: str = "project", *, project_dir: str | Path | None = None
) -> str:
    """Restore the most recent backup for an agent config."""
    if agent not in AGENTS:
        return f"Unknown agent: {agent}"
    return restore_backup(agent, str(scope), project_dir=project_dir)


def list_config_backups(
    agent: str, scope: str = "project", *, project_dir: str | Path | None = None
) -> str:
    """List available backups for an agent config."""
    if agent not in AGENTS:
        return f"Unknown agent: {agent}"
    backups = list_backups(agent, str(scope), project_dir=project_dir)
    if not backups:
        return f"No backups found for {agent} ({scope})."
    lines = [f"Backups for {agent} ({scope}):"]
    for b in backups:
        size = b.stat().st_size
        lines.append(f"  {b} ({size} bytes)")
    return "\n".join(lines)
