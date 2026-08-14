"""Interactive CLI setup wizard for kicad-mcp-pro.

Implements the rich terminal wizard described in the GUI spec (Phase 0 / Step 2).
Run via ``kicad-mcp-pro init --interactive`` or the standalone :func:`run_wizard`.
"""

from __future__ import annotations

import json
import os
import platform
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
# Platform-aware MCP client config paths
# ---------------------------------------------------------------------------

MCP_CLIENT_CONFIGS: dict[str, dict[str, str]] = {
    "claude-desktop": {
        "windows": "%APPDATA%\\Claude\\claude_desktop_config.json",
        "darwin": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "linux": "~/.config/Claude/claude_desktop_config.json",
    },
    "cursor": {
        "windows": "%APPDATA%\\Cursor\\User\\globalStorage\\cursor.mcp\\config.json",
        "darwin": "~/.cursor/mcp.json",
        "linux": "~/.cursor/mcp.json",
    },
    "vscode": {
        "windows": "%APPDATA%\\Code\\User\\settings.json",
        "darwin": "~/Library/Application Support/Code/User/settings.json",
        "linux": "~/.config/Code/User/settings.json",
    },
    "windsurf": {
        "windows": "%APPDATA%\\Windsurf\\mcp_config.json",
        "darwin": "~/.codeium/windsurf/mcp_config.json",
        "linux": "~/.codeium/windsurf/mcp_config.json",
    },
    "zed": {
        "windows": "~/.config/zed/settings.json",
        "darwin": "~/.config/zed/settings.json",
        "linux": "~/.config/zed/settings.json",
    },
}

CLIENT_DISPLAY_NAMES: dict[str, str] = {
    "claude-desktop": "Claude Desktop",
    "cursor": "Cursor",
    "vscode": "VS Code",
    "windsurf": "Windsurf",
    "zed": "Zed",
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
    """Write the MCP config snippet to the client's config file.

    Tries to merge with an existing ``mcpServers`` block when the file already
    exists.  Returns the config path on success or ``None`` if the path could
    not be resolved.
    """
    config_path = _resolve_config_path(client)
    if config_path is None:
        return None
    config_path = config_path.resolve()

    if config_path.exists():
        existing: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        existing = {}

    # Merge the snippet under mcpServers
    existing_servers = existing.get("mcpServers", {})
    existing_servers.update(snippet.get("mcpServers", {}))
    existing["mcpServers"] = existing_servers

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return config_path


def _generate_mcp_config(
    transport: str,
    port: int,
    version: str = __version__,
) -> dict[str, Any]:
    """Generate the ``mcpServers`` snippet for a client config file."""
    if transport == "stdio":
        args: list[str] = [f"kicad-mcp-pro@{version}"]
    else:
        args = [f"kicad-mcp-pro@{version}", "--transport", transport, "--port", str(port)]

    return {
        "mcpServers": {
            "kicad-mcp-pro": {
                "command": "uvx",
                "args": args,
                "env": {},
            }
        }
    }


def _write_kicad_mcp_config(
    kicad_path: Path,
    transport: str,
    port: int,
    output: Path | None = None,
) -> Path:
    """Write ``~/.kicad-mcp/config.json`` with the wizard choices."""
    config_path = output or (Path.home() / ".kicad-mcp" / "config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "kicad_path": str(kicad_path),
        "transport": transport,
        "port": port,
    }
    config_path.write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
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
            "[bold cyan]kicad-mcp-pro Kurulum Sihirbazi[/bold cyan]\nCikmak icin Ctrl+C",
            border_style="cyan",
        )
    )

    # ── 1. KiCad tespit ──────────────────────────────────────────
    console.print("\n[bold]1/4 — KiCad Yolu[/bold]")
    kicad_path = _detect_kicad_interactive(console, yes)
    if kicad_path is None:
        console.print("  [red]KiCad yolu gerekli. Kurulum iptal edildi.[/red]")
        raise typer.Exit(1)

    # ── 2. Transport modu ────────────────────────────────────────
    console.print("\n[bold]2/4 — Transport Modu[/bold]")
    transport, port = _select_transport_interactive(console, yes)

    # ── 3. MCP istemci ───────────────────────────────────────────
    console.print("\n[bold]3/4 — MCP Istemcisi[/bold]")
    client, client_display = _select_client_interactive(console, yes)

    # ── 4. Config uret ve yaz ────────────────────────────────────
    console.print("\n[bold]4/4 — Config Dosyasi[/bold]")
    snippet = _generate_mcp_config(transport, port)

    json_syntax = Syntax(
        json.dumps(snippet, indent=2, ensure_ascii=False),
        "json",
        theme="monokai",
    )
    console.print(json_syntax)

    # Write to client config
    if client and client != "none":
        if yes or typer.confirm(
            f"\n  {client_display} config dosyasina otomatik yazilsin mi?",
            default=True,
        ):
            written = _write_mcp_config(client, snippet)
            if written:
                console.print(f"  [green]Yazildi:[/green] {written}")
            else:
                console.print("  [yellow]Config dosyasi bulunamadi, manuel kopyalayin.[/yellow]")

    # Write ~/.kicad-mcp/config.json
    kicad_config_path = _write_kicad_mcp_config(kicad_path, transport, port, output)
    console.print(f"  [green]kicad-mcp-pro config:[/green] {kicad_config_path}")

    # ── 5. Summary ───────────────────────────────────────────────
    table = Table.grid(padding=(0, 2))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column()
    table.add_row("KiCad:", str(kicad_path))
    table.add_row("Transport:", transport)
    table.add_row("Port:", str(port) if transport != "stdio" else "(stdio)")
    table.add_row("Client:", client_display if client and client != "none" else "(atlanildi)")
    table.add_row("Config:", str(kicad_config_path))

    console.print()
    console.print(
        Panel.fit(
            "[bold green]Kurulum tamamlandi![/bold green]\n\n"
            "Baslatmak icin:\n"
            f"  [cyan]kicad-mcp-pro serve --transport {transport}[/cyan]\n\n"
            "Tray uygulamasi icin:\n"
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
            console.print(f"  [green]Kicad {version} bulundu:[/green] {cli_path}")
            if not yes:
                confirm = typer.confirm("  Bu yolu kullanayim mi?", default=True)
                if confirm:
                    return cli_path
    except Exception:
        console.print("  [yellow]Kicad otomatik bulunamadi.[/yellow]")

    # Manual entry
    while True:
        raw = typer.prompt("  Kicad yolunu girin (veya bos birakip iptal)", default="")
        if not raw.strip():
            return None
        candidate = Path(os.path.expandvars(os.path.expanduser(raw.strip())))
        if candidate.exists():
            return candidate
        console.print(f"  [red]Yol bulunamadi:[/red] {candidate}")


def _select_transport_interactive(console: Console, yes: bool) -> tuple[str, int]:
    """Step 2: choose transport and port."""
    if yes:
        return "streamable-http", 3334

    console.print("  1) streamable-http (Onerilen) — Claude Desktop, Cursor, Windsurf")
    console.print("  2) stdio — Sadece terminal tabanli istemciler")

    choice = typer.prompt("  Secim", default="1")
    transport = "streamable-http" if choice.strip() in ("1", "") else "stdio"

    port = 3334
    if transport == "streamable-http":
        port = typer.prompt("  Port", default=3334, type=int)

    return transport, port


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
        return "claude-desktop", display_map.get("claude-desktop", "Claude Desktop")

    console.print("  Hangi uygulamayi kullaniyorsunuz?")
    for i, c in enumerate(clients, 1):
        console.print(f"  {i}) {display_map.get(c, c)}")
    console.print(f"  {len(clients) + 1}) (Atla — config uretmeden bitir)")

    choice = typer.prompt("  Secim", default="1")
    choice = choice.strip()

    if choice == str(len(clients) + 1) or choice.lower() in ("skip", "none", ""):
        return "none", "(atlanildi)"

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(clients):
            c = clients[idx]
            return c, display_map.get(c, c)
    except ValueError:
        pass

    # Direct name match
    if choice in clients:
        return choice, display_map.get(choice, choice)
    if choice in display_map.values():
        for c, d in display_map.items():
            if d.lower() == choice.lower():
                return c, d

    # Fallback
    console.print("  [yellow]Gecersiz secim, varsayilan kullaniliyor.[/yellow]")
    return "claude-desktop", display_map.get("claude-desktop", "Claude Desktop")
