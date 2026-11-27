"""Interactive CLI setup wizard for kicad-mcp-pro.

Implements the rich terminal wizard described in the GUI spec (Phase 0 / Step 2).
Run via ``kicad-mcp-pro init --interactive`` or the standalone :func:`run_wizard`.
"""

from __future__ import annotations

import json
import os
import platform
import re
import tomllib
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from kicad_mcp import __version__
from kicad_mcp.discovery import discover_kicad_cli, find_kicad_version

# ---------------------------------------------------------------------------
# Named constants for transports and MCP client identifiers
# ---------------------------------------------------------------------------

TRANSPORT_STREAMABLE_HTTP = "streamable-http"
TRANSPORT_STDIO = "stdio"
DEFAULT_HTTP_PORT = 3334

CLIENT_CLAUDE_DESKTOP = "claude-desktop"
CLIENT_CURSOR = "cursor"
CLIENT_VSCODE = "vscode"
CLIENT_WINDSURF = "windsurf"
CLIENT_ZED = "zed"

CLIENT_NONE = "none"
CLIENT_SKIPPED_DISPLAY = "(skipped)"

_ZED_UNIX_CONFIG_PATH = "~/.config/zed/settings.json"
_ZED_WINDOWS_CONFIG_PATH = r"%APPDATA%\Zed\settings.json"
_CLAUDE_DESKTOP_DISPLAY_NAME = "Claude Desktop"

# ---------------------------------------------------------------------------
# Platform-aware MCP client config paths
# ---------------------------------------------------------------------------

MCP_CLIENT_CONFIGS: dict[str, dict[str, str]] = {
    CLIENT_CLAUDE_DESKTOP: {
        "windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
        "darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "linux": "~/.config/Claude/claude_desktop_config.json",
    },
    CLIENT_CURSOR: {
        "windows": "~/.cursor/mcp.json",
        "darwin": "~/.cursor/mcp.json",
        "linux": "~/.cursor/mcp.json",
    },
    CLIENT_VSCODE: {
        "windows": "%APPDATA%\\Code\\User\\mcp.json",
        "darwin": "~/Library/Application Support/Code/User/mcp.json",
        "linux": "~/.config/Code/User/mcp.json",
    },
    CLIENT_WINDSURF: {
        "windows": "~/.codeium/windsurf/mcp_config.json",
        "darwin": "~/.codeium/windsurf/mcp_config.json",
        "linux": "~/.codeium/windsurf/mcp_config.json",
    },
    CLIENT_ZED: {
        "windows": _ZED_WINDOWS_CONFIG_PATH,
        "darwin": _ZED_UNIX_CONFIG_PATH,
        "linux": _ZED_UNIX_CONFIG_PATH,
    },
}

CLIENT_DISPLAY_NAMES: dict[str, str] = {
    CLIENT_CLAUDE_DESKTOP: _CLAUDE_DESKTOP_DISPLAY_NAME,
    CLIENT_CURSOR: "Cursor",
    CLIENT_VSCODE: "VS Code",
    CLIENT_WINDSURF: "Windsurf",
    CLIENT_ZED: "Zed",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_config_path(client: str) -> Path | None:
    """Resolve the configuration file path for a client on the current platform."""
    candidates = MCP_CLIENT_CONFIGS.get(client)
    if not candidates:
        return None
    sys_key = platform.system().lower()
    if sys_key == "darwin":
        sys_key = "darwin"
    raw = candidates.get(sys_key) or candidates.get("linux", "")
    if not raw:
        return None
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return Path(expanded)


def _write_mcp_config(client: str, snippet: dict[str, Any]) -> Path | None:
    """Write the MCP config snippet to the client's config file safely.

    Merges safely under mcpServers, keeps backup, and records ownership.
    """
    config_path = _resolve_config_path(client)
    if config_path is None:
        return None
    write_target = config_path.expanduser().resolve()

    # Pre-render via json.dumps to trigger any configured/hooked serialization
    # while pinning the resolved target path against symlink retargeting.
    _ = json.dumps(snippet)

    from kicad_mcp.services.client_config import write_client_config_safe

    res = write_client_config_safe(client, write_target, snippet)
    if res.success:
        return config_path
    return None


def _generate_mcp_config(
    transport: str,
    port: int,
    version: str = __version__,
    *,
    client: str = CLIENT_CURSOR,
) -> dict[str, Any]:
    """Generate a client-native launcher or endpoint, never HTTP over stdio."""
    if transport not in {TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP}:
        raise ValueError("Unsupported transport.")
    if transport == TRANSPORT_STREAMABLE_HTTP and not 1 <= port <= 65535:
        raise ValueError("HTTP port must be between 1 and 65535.")
    if client == CLIENT_CLAUDE_DESKTOP and transport != TRANSPORT_STDIO:
        raise ValueError("Claude Desktop local configuration requires stdio.")
    namespace = {
        CLIENT_VSCODE: "servers",
        CLIENT_ZED: "context_servers",
    }.get(client, "mcpServers")
    entry: dict[str, Any]
    if transport == TRANSPORT_STDIO:
        entry = {
            "command": "uvx",
            "args": [f"kicad-mcp-pro@{version}"],
            "env": {"KICAD_MCP_TRANSPORT": "stdio"},
        }
        if client == CLIENT_VSCODE:
            entry["type"] = "stdio"
    else:
        endpoint = f"http://127.0.0.1:{port}/mcp"
        entry = {"serverUrl" if client == CLIENT_WINDSURF else "url": endpoint}
        if client in {CLIENT_VSCODE, CLIENT_CURSOR}:
            entry["type"] = "http"
    return {namespace: {"kicad-mcp-pro": entry}}


def _merge_runtime_settings(existing: str, updates: dict[str, str | int]) -> str:
    """Edit only simple root settings; prove all unrelated TOML values survive."""
    before = tomllib.loads(existing)
    rendered = existing
    for key in updates:
        # Complex spellings or multiline values are not rewritten. The
        # semantic check below rejects duplicates or any collateral edit.
        rendered = (
            re.sub(
                rf"(?m)^[ \t]*{re.escape(key)}[ \t]*=[^\r\n]*(?:\r?\n|$)",
                "",
                rendered,
                count=1,
            )
            if key in before
            else rendered
        )
    prefix = "".join(
        f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in updates.items()
    )
    merged = prefix + rendered
    if tomllib.loads(merged) != {**before, **updates}:
        raise ValueError("Existing config uses complex settings; edit the runtime TOML manually.")
    return merged


def _write_kicad_mcp_config(
    kicad_path: Path,
    transport: str,
    port: int,
    output: Path | None = None,
) -> Path:
    """Write the trusted TOML file actually read by KiCadMCPConfig."""
    from kicad_mcp.config import CONFIG_FILE
    from kicad_mcp.setup import _atomic_write_text

    if transport not in {TRANSPORT_STDIO, TRANSPORT_STREAMABLE_HTTP}:
        raise ValueError("Unsupported transport.")
    if transport == TRANSPORT_STREAMABLE_HTTP and not 1 <= port <= 65535:
        raise ValueError("HTTP port must be between 1 and 65535.")
    config_path = (output or CONFIG_FILE).expanduser().resolve()
    existing = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    before = tomllib.loads(existing)
    if transport == TRANSPORT_STREAMABLE_HTTP and (
        before.get("host", "127.0.0.1") not in {"127.0.0.1", "localhost"}
        or before.get("mount_path", "/mcp") != "/mcp"
        or before.get("http_boundary", "direct") != "direct"
        or before.get("tls_cert_file")
        or before.get("auth_token")
    ):
        raise ValueError("Existing protected/custom HTTP settings require manual configuration.")
    updates: dict[str, str | int] = {
        "kicad_cli": str(kicad_path),
        "transport": transport,
        "port": port if transport != TRANSPORT_STDIO else DEFAULT_HTTP_PORT,
    }
    merged = _merge_runtime_settings(existing, updates)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(config_path, merged)
    return config_path


# ---------------------------------------------------------------------------
# Interactive wizard
# ---------------------------------------------------------------------------


def run_wizard(
    yes: bool = False,
    output: Path | None = None,
) -> None:
    """Launch the interactive terminal wizard (blocking)."""
    console = Console()

    console.print(
        Panel.fit(
            "[bold cyan]kicad-mcp-pro Setup Wizard[/bold cyan]\nPress Ctrl+C to exit",
            border_style="cyan",
        )
    )

    # ── 1. KiCad tespit ──────────────────────────────────────────
    console.print("\n[bold]1/4 — KiCad Path[/bold]")
    kicad_path = _detect_kicad_interactive(console, yes)
    if kicad_path is None:
        console.print("  [red]KiCad path is required. Setup canceled.[/red]")
        raise typer.Exit(1)

    # ── 2. Transport modu ────────────────────────────────────────
    console.print("\n[bold]2/4 — Transport Mode[/bold]")
    transport, port = _select_transport_interactive(console, yes)

    # ── 3. MCP istemci ───────────────────────────────────────────
    console.print("\n[bold]3/4 — MCP Client[/bold]")
    client, client_display = _select_client_interactive(console, yes)

    # ── 4. Config uret ve yaz ────────────────────────────────────
    console.print("\n[bold]4/4 — Config File[/bold]")
    try:
        snippet = _generate_mcp_config(transport, port, client=client)
        kicad_config_path = _write_kicad_mcp_config(kicad_path, transport, port, output)
    except (OSError, ValueError) as exc:
        console.print(f"  [red]Setup could not save configuration: {exc}[/red]")
        raise typer.Exit(1) from exc

    json_syntax = Syntax(
        json.dumps(snippet, indent=2, ensure_ascii=False),
        "json",
        theme="monokai",
    )
    console.print(json_syntax)

    # Write to client config
    if client and client != CLIENT_NONE:
        if yes or typer.confirm(
            f"\n  {client_display} config file automatically?",
            default=True,
        ):
            written = _write_mcp_config(client, snippet)
            if written:
                console.print(f"  [green]Written:[/green] {written}")
            else:
                console.print("  [yellow]Config file not found, please copy manually.[/yellow]")

    console.print(f"  [green]kicad-mcp-pro config:[/green] {kicad_config_path}")

    # ── 5. Summary ───────────────────────────────────────────────
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("KiCad:", str(kicad_path))
    table.add_row("Transport:", transport)
    table.add_row("Port:", str(port) if transport != TRANSPORT_STDIO else "(stdio)")
    table.add_row(
        "Client:", client_display if client and client != CLIENT_NONE else CLIENT_SKIPPED_DISPLAY
    )
    table.add_row("Config:", str(kicad_config_path))

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Setup completed![/bold green]\n\n"
            "To start:\n"
            f"  [cyan]kicad-mcp-pro serve --transport {transport}"
            + (f" --host 127.0.0.1 --port {port}" if transport == TRANSPORT_STREAMABLE_HTTP else "")
            + "[/cyan]\n\n"
            "For tray app:\n"
            "  [cyan]kicad-mcp-pro tray[/cyan]",
            border_style="green",
        )
    )
    console.print(table)


def _detect_kicad_interactive(console: Console, yes: bool) -> Path | None:
    """Step 1: detect or ask for KiCad path."""
    try:
        cli_path = discover_kicad_cli()
        version = find_kicad_version(cli_path)
        if version:
            console.print(f"  [green]Found KiCad {version}:[/green] {cli_path}")
            if yes or typer.confirm("  Use this path?", default=True):
                return cli_path
    except Exception:
        console.print("  [yellow]KiCad not found automatically.[/yellow]")

    if yes:
        return None

    # Manual entry
    while True:
        raw = typer.prompt("  Enter KiCad path (or leave blank to cancel)", default="")
        if not raw.strip():
            return None
        candidate = Path(os.path.expandvars(os.path.expanduser(raw.strip())))
        if candidate.exists():
            return candidate
        console.print(f"  [red]Path not found:[/red] {candidate}")


def _select_transport_interactive(console: Console, yes: bool) -> tuple[str, int]:
    """Step 2: choose transport and port."""
    if yes:
        return TRANSPORT_STDIO, DEFAULT_HTTP_PORT

    console.print(f"  1) {TRANSPORT_STREAMABLE_HTTP} - local HTTP endpoint")
    console.print(f"  2) {TRANSPORT_STDIO} (Recommended) - client-managed process")

    choice = typer.prompt("  Choice", default="2")
    transport = TRANSPORT_STREAMABLE_HTTP if choice.strip() == "1" else TRANSPORT_STDIO

    port = DEFAULT_HTTP_PORT
    if transport == TRANSPORT_STREAMABLE_HTTP:
        port = typer.prompt("  Port", default=DEFAULT_HTTP_PORT, type=int)

    return transport, port


def _match_client_choice(
    choice: str, clients: list[str], display_map: dict[str, str]
) -> tuple[str, str] | None:
    """Resolve a numeric, internal, or displayed client name without fallback."""
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(clients):
            client = clients[idx]
            return client, display_map.get(client, client)
    except ValueError:
        pass

    if choice in clients:
        return choice, display_map.get(choice, choice)
    if choice in display_map.values():
        for client, display in display_map.items():
            if display.lower() == choice.lower():
                return client, display
    return None


def _select_client_interactive(
    console: Console,
    yes: bool,
) -> tuple[str, str]:
    """Step 3: choose an MCP client."""
    clients = list(MCP_CLIENT_CONFIGS.keys())
    display_map = dict(CLIENT_DISPLAY_NAMES)

    if yes:
        # Auto-detect: find the first client whose config file already exists
        for c in clients:
            path = _resolve_config_path(c)
            if path and path.exists():
                return c, display_map.get(c, c)
        return CLIENT_CLAUDE_DESKTOP, display_map.get(
            CLIENT_CLAUDE_DESKTOP, _CLAUDE_DESKTOP_DISPLAY_NAME
        )

    console.print("  Which client application are you using?")
    for i, c in enumerate(clients, 1):
        console.print(f"  {i}) {display_map.get(c, c)}")
    console.print(f"  {len(clients) + 1}) (Skip — finish without generating config)")

    choice = typer.prompt("  Choice", default="1")
    choice = choice.strip()

    if choice == str(len(clients) + 1) or choice.lower() in ("skip", "none", ""):
        return CLIENT_NONE, CLIENT_SKIPPED_DISPLAY

    selected = _match_client_choice(choice, clients, display_map)
    if selected is not None:
        return selected

    # Fallback
    console.print("  [yellow]Invalid choice, using default.[/yellow]")
    return CLIENT_CLAUDE_DESKTOP, display_map.get(
        CLIENT_CLAUDE_DESKTOP, _CLAUDE_DESKTOP_DISPLAY_NAME
    )
