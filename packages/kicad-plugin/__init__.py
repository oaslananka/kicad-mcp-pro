"""KiCad companion Action Plugin for kicad-mcp (issue #157).

Copy or symlink this directory into your KiCad plugins folder
(``Preferences -> Plugin and Content Manager``, or the platform plugin path) and
KiCad's pcbnew will auto-register the toolbar action on startup.

The plugin reads the live board read-only, publishes the active project / file /
selection context to a running kicad-mcp-pro server, and gates any mutating action
behind a safe-apply confirmation. It requires no broad permissions: it talks only
to the loopback MCP endpoint and never writes files itself.
"""

from __future__ import annotations

# KiCad executes this file inside its bundled Python. Registration must not raise
# if the optional pieces are missing, so failures are surfaced to the KiCad log
# rather than aborting plugin discovery for every other plugin.
try:  # pragma: no cover - exercised only inside KiCad
    from .kicad_mcp_companion import KiCadMcpCompanionPlugin

    KiCadMcpCompanionPlugin().register()
except Exception as exc:  # noqa: BLE001 - never break KiCad plugin discovery
    import logging

    logging.getLogger(__name__).warning("kicad-mcp companion plugin failed to load: %s", exc)
