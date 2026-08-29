"""pcbnew Action Plugin entry point for the kicad-mcp companion (issue #157).

This module is only imported inside KiCad (it depends on ``pcbnew`` and ``wx``).
All testable logic lives in ``context.py`` (vendored alongside this plugin from
``kicad_mcp.companion.context``); this file is the thin GUI shim that reads the
live board and drives that logic. The plugin is self-contained — it needs no
``KICAD_MCP_HOME`` and no system-wide install.
"""

from __future__ import annotations

import os
import sys
import threading
from types import ModuleType

import pcbnew  # type: ignore[import-not-found]  # provided by KiCad


def _ensure_companion_importable() -> None:
    """Add a kicad-mcp checkout to ``sys.path`` (dev fallback when not vendored)."""
    home = os.environ.get("KICAD_MCP_HOME")
    if home:
        src = os.path.join(home, "src")
        for path in (src, home):
            if os.path.isdir(path) and path not in sys.path:
                sys.path.insert(0, path)


def _load_context() -> ModuleType:
    """Return the companion context module.

    Prefers the ``context.py`` vendored next to this plugin so it works out of the
    box inside KiCad's bundled Python. Falls back to an installed ``kicad_mcp``
    package (optionally located via ``KICAD_MCP_HOME``) for source checkouts.
    """
    try:
        from . import context as ctx

        return ctx
    except ImportError:
        try:
            import context as ctx

            return ctx
        except ImportError:
            _ensure_companion_importable()
            from kicad_mcp.companion import context as ctx

            return ctx


class KiCadMcpCompanionPlugin(pcbnew.ActionPlugin):
    """Publish live KiCad context to kicad-mcp and gate mutating actions."""

    def defaults(self) -> None:
        self.name = "kicad-mcp companion"
        self.category = "kicad-mcp"
        self.description = "Publish active board context to a running kicad-mcp-pro server."
        self.show_toolbar_button = True

    def Run(self) -> None:
        import wx  # type: ignore[import-not-found]  # provided by KiCad

        try:
            ctx = _load_context()
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            wx.MessageBox(
                "kicad-mcp companion helpers not found.\n"
                "Reinstall the plugin (it should contain context.py), or set "
                f"KICAD_MCP_HOME to a kicad-mcp checkout.\n\n{exc}",
                "kicad-mcp companion",
                wx.ICON_ERROR,
            )
            return

        info = self._read_board_info(ctx.BoardInfo)
        base_url = os.environ.get("KICAD_MCP_URL", "http://127.0.0.1:3334")
        auth_token = os.environ.get("KICAD_MCP_AUTH_TOKEN", "")
        threading.Thread(
            target=self._run_backend_flow,
            args=(ctx, info, base_url, auth_token, wx),
            name="kicad-mcp-companion",
            daemon=True,
        ).start()

    def _run_backend_flow(
        self,
        ctx: ModuleType,
        info: object,
        base_url: str,
        auth_token: str,
        wx: object,
    ) -> None:
        def show(message: str, icon: object) -> None:
            wx.CallAfter(wx.MessageBox, message, "kicad-mcp companion", icon)

        try:
            compatibility = ctx.load_compatibility_contract()
            client = ctx.StudioContextClient(base_url, auth_token=auth_token)
            health = client.health(compatibility)
            if health.state != "ready":
                show(
                    f"{health.message}\n\n"
                    "Recovery: start or update the local kicad-mcp-pro backend, then retry.",
                    wx.ICON_ERROR,
                )
                return
            client.push(ctx.build_studio_context(info))
            file_name = getattr(info, "file_name", "")
            show(
                f"Pushed context for {file_name or 'active board'} to {base_url}.",
                wx.ICON_INFORMATION,
            )
        except ValueError as exc:
            show(f"Companion setup/compatibility error:\n{exc}", wx.ICON_ERROR)
        except Exception as exc:  # noqa: BLE001 - network/server errors are user-facing
            show(
                f"Could not reach kicad-mcp at {base_url}:\n{exc}\n\n"
                "Start an HTTP-mode server, e.g.:\n"
                "kicad-mcp-pro --transport streamable-http --port 3334 --mode write",
                wx.ICON_ERROR,
            )

    def _read_board_info(self, board_info_cls: type) -> object:
        board = pcbnew.GetBoard()
        file_name = board.GetFileName() if board else ""
        project_root = os.path.dirname(file_name) if file_name else ""
        selected_reference = ""
        for footprint in board.GetFootprints() if board else []:
            if footprint.IsSelected():
                selected_reference = footprint.GetReference()
                break
        return board_info_cls(
            file_name=file_name,
            file_type="pcb",
            project_root=project_root,
            project_file=file_name,
            selected_reference=selected_reference,
            selected_net="",
        )

    @staticmethod
    def confirm_safe_apply(action: str) -> bool:
        """Show a confirmation dialog before a mutating action; return user choice."""
        import wx  # type: ignore[import-not-found]

        ctx = _load_context()
        if not ctx.requires_confirmation(action):
            return True
        result = wx.MessageBox(
            f"Allow kicad-mcp to apply '{action}' to the board?",
            "kicad-mcp safe apply",
            wx.YES_NO | wx.ICON_WARNING,
        )
        return result == wx.YES
