"""Deprecated tool aliases and a one-time deprecation notice (work order P1-T1).

A canonical tool keeps its name; a superseded duplicate is registered as an alias so
existing clients keep working, but each alias logs a single deprecation warning the
first time it is used and is recorded in :data:`ALIASES` for discovery and docs.

This is the central registrar for the "one canonical tool per capability" rule. See
``docs/adr/0003-export-tool-naming.md``.
"""

from __future__ import annotations

from collections.abc import Callable

import structlog
from mcp.server.mcpserver import MCPServer as FastMCP

logger = structlog.get_logger(__name__)

# Deprecated alias tool name -> canonical tool name.
ALIASES: dict[str, str] = {}
_warned: set[str] = set()


def notify_deprecated(alias: str) -> None:
    """Log a one-time deprecation warning for a deprecated alias tool."""
    if alias in _warned:
        return
    _warned.add(alias)
    canonical = ALIASES.get(alias, "")
    logger.warning(
        "deprecated_tool_alias",
        alias=alias,
        canonical=canonical,
        message=f"'{alias}' is a deprecated alias for '{canonical}'; prefer '{canonical}'.",
    )


def register_alias[**P, R](
    mcp: FastMCP, alias_fn: Callable[P, R], canonical: str
) -> Callable[P, R]:
    """Register ``alias_fn`` as a deprecated alias that delegates to ``canonical``.

    The alias function body is expected to call :func:`notify_deprecated` and then
    delegate to the canonical tool.
    """
    ALIASES[alias_fn.__name__] = canonical
    mcp.tool()(alias_fn)
    return alias_fn
