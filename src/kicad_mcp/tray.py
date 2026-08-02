"""System tray application for KiCad MCP Pro.

Provides a pystray icon with context menu for:
  - Starting/stopping the MCP server
  - Opening the web dashboard
  - Quick DRC and status checks
  - Graceful shutdown

Usage:
    kicad-mcp-pro tray
"""

from __future__ import annotations

import importlib.util as _importlib_util
import os
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Optional PIL / pystray imports
# ---------------------------------------------------------------------------

_HAS_TRAY = False
_HAS_PIL = False
_tray_module: Any = None

# PIL can be available even without pystray (used for icon generation)
try:
    from PIL import Image, ImageDraw  # noqa: F401

    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False

_HAS_TRAY = _HAS_PIL and _importlib_util.find_spec("pystray") is not None


# ---------------------------------------------------------------------------
# Icon generation
# ---------------------------------------------------------------------------

_STATUS_COLORS: dict[str, tuple[int, int, int]] = {
    "running": (34, 197, 94),
    "stopped": (156, 163, 175),
    "error": (234, 179, 8),
    "starting": (59, 130, 246),
}


def _create_icon(status: str = "stopped") -> Image.Image:
    """Create a 64x64 tray icon (KiCad-style MCP logo)."""
    if not _HAS_PIL:
        msg = "PIL (Pillow) is required for icon generation"
        raise ImportError(msg)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw a rounded rectangle with circuit-board accent
    margin = 4
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=8,
        fill=(13, 17, 23),
        outline=(88, 166, 255),
        width=2,
    )

    # Draw "K M" text (simplified circuit-like shape)
    cx, cy = size // 2, size // 2
    # Left vertical (K)
    draw.line([(cx - 12, cy - 12), (cx - 12, cy + 12)], fill=(88, 166, 255), width=3)
    draw.line([(cx - 12, cy), (cx + 4, cy - 12)], fill="white", width=2)
    draw.line([(cx - 12, cy), (cx + 4, cy + 12)], fill="white", width=2)
    # Right (M)
    draw.line([(cx + 4, cy - 12), (cx + 4, cy + 12)], fill=(88, 166, 255), width=3)

    # Connection dots (like circuit nodes)
    draw.ellipse([(cx - 15, cy - 15), (cx - 9, cy - 9)], fill=(63, 185, 80))
    draw.ellipse([(cx + 1, cy + 7), (cx + 7, cy + 13)], fill=(63, 185, 80))
    status_color = _STATUS_COLORS.get(status, _STATUS_COLORS["stopped"])
    draw.ellipse([46, 46, 62, 62], fill=(*status_color, 255), outline=(255, 255, 255, 220))

    return img


# ---------------------------------------------------------------------------
# Tray application
# ---------------------------------------------------------------------------


class KiCadTrayApp:
    """System tray application managing the KiCad MCP Pro server lifecycle."""

    def __init__(self, port: int = 3334) -> None:
        self._server_proc: subprocess.Popen[bytes] | None = None
        self._server_port: int = port
        self._running = False
        self._icon: Any = None
        self._thread: threading.Thread | None = None
        self._dashboard_url = f"http://127.0.0.1:{self._server_port}/ui"

    # -- Public API ---------------------------------------------------------

    def run(self) -> None:
        """Start the system tray application (blocking)."""
        if not _HAS_TRAY:
            logger.error(
                "pystray_not_available",
                message="pystray is not installed. Install with: pip install kicad-mcp-pro[tray]",
            )
            print("Error: pystray is not installed.", file=sys.stderr)
            print(
                "Install it with: pip install kicad-mcp-pro[tray] or pip install pystray Pillow",
                file=sys.stderr,
            )
            sys.exit(1)

        import pystray as _tray_module  # type: ignore[import-not-found, import-untyped, unused-ignore]

        self._running = True
        icon = _tray_module.Icon(
            "kicad-mcp-pro",
            _create_icon("stopped"),
            "KiCad MCP Pro",
            menu=self._build_menu(),
        )
        self._icon = icon

        # Handle SIGINT gracefully
        signal.signal(signal.SIGINT, lambda *_: icon.stop())

        icon.run()

    def stop(self) -> None:
        """Stop the tray app and shut down the server."""
        self._stop_server()
        self._running = False
        if self._icon:
            self._icon.stop()

    # -- Menu construction -------------------------------------------------

    def _build_menu(self) -> Any:  # noqa: ANN401
        """Build the pystray context menu."""
        import pystray as _pst

        return _pst.Menu(
            _pst.MenuItem("Open Dashboard", self._action_open_dashboard, default=True),
            _pst.Menu.SEPARATOR,
            _pst.MenuItem("Start Server", self._action_start_server),
            _pst.MenuItem("Stop Server", self._action_stop_server),
            _pst.MenuItem("Restart Server", self._action_restart_server),
            _pst.Menu.SEPARATOR,
            _pst.MenuItem("Settings", lambda *_: self._open_dashboard_route("settings")),
            _pst.MenuItem("Logs", lambda *_: self._open_dashboard_route("logs")),
            _pst.Menu.SEPARATOR,
            _pst.MenuItem("Run DRC", self._action_run_drc),
            _pst.MenuItem("Export Gerber", self._action_export_gerber),
            _pst.MenuItem("Show Status", self._action_show_status),
            _pst.Menu.SEPARATOR,
            _pst.MenuItem("Quit", self._action_quit),
        )

    # -- Actions -----------------------------------------------------------

    def _action_start_server(self) -> None:
        """Start the MCP server process."""
        if self._server_proc and self._server_proc.poll() is None:
            logger.info("tray_server_already_running")
            return

        env = os.environ.copy()
        env.setdefault("KICAD_MCP_TRANSPORT", "streamable-http")
        env.setdefault("KICAD_MCP_HOST", "127.0.0.1")
        env.setdefault("KICAD_MCP_PORT", str(self._server_port))

        try:
            self._update_icon("starting")
            self._server_proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "kicad_mcp.server",
                    "dashboard",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(self._server_port),
                ],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            self._update_icon("running")
            logger.info("tray_server_started", pid=self._server_proc.pid, port=self._server_port)
            self._show_notification(f"Server started on port {self._server_port}")
        except Exception as exc:
            self._update_icon("error")
            logger.error("tray_server_start_failed", error=str(exc))
            self._show_notification(f"Failed to start server: {exc}")

    def _action_stop_server(self) -> None:
        """Stop the MCP server process."""
        self._stop_server()
        self._show_notification("Server stopped")

    def _action_restart_server(self) -> None:
        """Restart the MCP server process."""
        self._stop_server()
        self._action_start_server()

    def _action_open_dashboard(self) -> None:
        """Open the web dashboard in the default browser."""
        import webbrowser

        logger.info("tray_opening_dashboard", url=self._dashboard_url)
        try:
            # Start server if not running
            if not (self._server_proc and self._server_proc.poll() is None):
                self._action_start_server()
                time.sleep(1)  # brief wait for startup
            webbrowser.open(self._dashboard_url)
        except Exception as exc:
            logger.error("tray_dashboard_failed", error=str(exc))

    def _open_dashboard_route(self, route: str) -> None:
        """Open a hash-routed dashboard view."""
        import webbrowser

        webbrowser.open(f"{self._dashboard_url}#/{route}")

    def _action_run_drc(self) -> None:
        """Run DRC through the canonical typed validation runner."""
        try:
            from .config import get_config
            from .discovery import get_cli_capabilities
            from .tools.export_support import _run_cli_variants
            from .validation.drc_runner import run_drc_report

            cfg = get_config()
            if not cfg.pcb_file or not cfg.pcb_file.exists():
                self._show_notification("No PCB file configured")
                return

            result = run_drc_report(
                "tray_drc_report.json",
                pcb_file=cfg.pcb_file,
                output_dir=cfg.ensure_output_dir("drc"),
                run_cli_variants=_run_cli_variants,
                capabilities=get_cli_capabilities(cfg.kicad_cli),
            )
            if result.status == "clean":
                summary = "DRC completed with no findings"
            elif result.status == "findings":
                summary = "DRC completed with design findings"
            elif result.status == "malformed":
                summary = f"DRC report malformed: {result.error or 'unknown schema error'}"
            else:
                summary = f"DRC unavailable: {result.error or 'unknown error'}"
            self._show_notification(summary[:200])
            logger.info(
                "tray_drc_completed",
                status=result.status,
                returncode=result.return_code,
                report_path=str(result.path),
            )
        except Exception as exc:
            logger.error("tray_drc_failed", error=str(exc))
            self._show_notification(f"DRC failed: {exc}")

    def _action_export_gerber(self) -> None:
        """Export Gerber files."""
        try:
            from .config import get_config

            cfg = get_config()
            if cfg.pcb_file and cfg.pcb_file.exists():
                output_dir = cfg.ensure_output_dir("gerber")
                subprocess.run(
                    [
                        str(cfg.kicad_cli),
                        "pcb",
                        "export",
                        "gerber",
                        "-o",
                        str(output_dir),
                        str(cfg.pcb_file),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                self._show_notification(f"Gerber exported to {output_dir}")
                logger.info("tray_gerber_exported", output=str(output_dir))
            else:
                self._show_notification("No PCB file configured")
        except Exception as exc:
            logger.error("tray_gerber_failed", error=str(exc))
            self._show_notification(f"Gerber export failed: {exc}")

    def _action_show_status(self) -> None:
        """Show a brief status notification."""
        try:
            from .diagnostics import build_health_report

            report = build_health_report()
            status_text = f"Status: {report.status}\n"
            for c in report.checks[:5]:
                icon = "✅" if c.status == "ok" else "⚠️"
                status_text += f"{icon} {c.name}: {c.message[:50]}\n"
            self._show_notification(status_text.strip())
        except Exception as exc:
            self._show_notification(f"Status error: {exc}")

    def _action_quit(self) -> None:
        """Quit the tray application."""
        self.stop()

    # -- Helpers -----------------------------------------------------------

    def _stop_server(self) -> None:
        if self._server_proc and self._server_proc.poll() is None:
            logger.info("tray_stopping_server", pid=self._server_proc.pid)
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()
                self._server_proc.wait()
            self._server_proc = None
        self._update_icon("stopped")

    def _show_notification(self, message: str) -> None:
        """Show a desktop notification if supported."""
        if self._icon and hasattr(self._icon, "notify"):
            try:
                self._icon.notify(message, title="KiCad MCP Pro")
            except Exception as exc:
                logger.debug("tray_notification_failed", error=str(exc))

    def _update_icon(self, status: str) -> None:
        """Update tray icon image and tooltip for the current server state."""
        if self._icon:
            try:
                self._icon.icon = _create_icon(status)
                self._icon.title = f"KiCad MCP Pro [{status}]"
            except Exception as exc:
                logger.debug("tray_icon_update_failed", error=str(exc))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def tray_main(port: int = 3334) -> None:
    """Launch the system tray application."""
    if not _HAS_TRAY:
        print("Error: pystray is not installed.", file=sys.stderr)
        print(
            "Install it with: pip install kicad-mcp-pro[tray] or pip install pystray Pillow",
            file=sys.stderr,
        )
        sys.exit(1)

    app = KiCadTrayApp(port=port)
    try:
        app.run()
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    tray_main()
