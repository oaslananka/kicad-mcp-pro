"""KiCad MCP Pro server entrypoint."""

from __future__ import annotations

import os

import structlog
import typer
from mcp.server.fastmcp import FastMCP

from . import __version__
from .config import get_config, reset_config
from .prompts import workflows
from .resources import board_state
from .tools import export, library, pcb, project, router, routing, schematic, simulation, validation
from .tools.router import categories_for_profile
from .utils.logging import setup_logging

logger = structlog.get_logger(__name__)
app = typer.Typer(help="KiCad MCP Pro server for PCB and schematic workflows.")


def build_server(profile: str | None = None) -> FastMCP:
    """Build a FastMCP server instance for the active profile."""
    cfg = get_config()
    selected_profile = profile or cfg.profile
    server = FastMCP(
        name="kicad-mcp-pro",
        instructions=(
            "KiCad MCP Pro Server for project setup, schematic capture, PCB editing, "
            "validation, and manufacturing export. Start with kicad_get_version() "
            "and kicad_set_project()."
        ),
        host=cfg.host,
        port=cfg.port,
        streamable_http_path=cfg.mount_path,
        mount_path=cfg.mount_path,
        log_level=cfg.log_level,
    )

    router.register(server)
    project.register(server)

    enabled = set(categories_for_profile(selected_profile))
    if "pcb_read" in enabled or "pcb_write" in enabled:
        pcb.register(server)
    if "schematic" in enabled:
        schematic.register(server)
    if "library" in enabled:
        library.register(server)
    if "export" in enabled:
        export.register(server)
    if "validation" in enabled:
        validation.register(server)
    if "routing" in enabled:
        routing.register(server)
    if "simulation" in enabled:
        simulation.register(server)

    board_state.register(server)
    workflows.register(server)
    return server


@app.callback(invoke_without_command=True)
def main_callback(
    transport: str = typer.Option("stdio", help="Transport: stdio, http, sse, streamable-http"),
    host: str = typer.Option("127.0.0.1", help="HTTP bind host"),
    port: int = typer.Option(3334, help="HTTP bind port"),
    project_dir: str | None = typer.Option(None, help="Active KiCad project directory"),
    log_level: str = typer.Option("INFO", help="Log level"),
    log_format: str = typer.Option("console", help="Log format: console or json"),
    profile: str = typer.Option(
        "full", help="Server profile: full, minimal, pcb, schematic, manufacturing"
    ),
    experimental: bool = typer.Option(False, help="Enable experimental tools"),
) -> None:
    """Start the KiCad MCP Pro server."""
    os.environ["KICAD_MCP_TRANSPORT"] = transport
    os.environ["KICAD_MCP_HOST"] = host
    os.environ["KICAD_MCP_PORT"] = str(port)
    os.environ["KICAD_MCP_LOG_LEVEL"] = log_level
    os.environ["KICAD_MCP_LOG_FORMAT"] = log_format
    os.environ["KICAD_MCP_PROFILE"] = profile
    os.environ["KICAD_MCP_ENABLE_EXPERIMENTAL_TOOLS"] = "true" if experimental else "false"
    if project_dir:
        os.environ["KICAD_MCP_PROJECT_DIR"] = project_dir

    reset_config()
    cfg = get_config()
    setup_logging(cfg.log_level, cfg.log_format)

    selected_transport = "stdio" if cfg.transport == "stdio" else "streamable-http"
    server = build_server(cfg.profile)
    logger.info(
        "starting_kicad_mcp_pro",
        version=__version__,
        transport=selected_transport,
        profile=cfg.profile,
    )

    if selected_transport == "stdio":
        server.run(transport="stdio")
        return

    server.run(transport="streamable-http", mount_path=cfg.mount_path)


def main() -> None:
    """CLI entrypoint used by the package script."""
    app()


if __name__ == "__main__":
    main()
