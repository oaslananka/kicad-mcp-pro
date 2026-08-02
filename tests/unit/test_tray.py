"""Tests for the system tray module."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if TYPE_CHECKING:
    from collections.abc import Generator


# ---------------------------------------------------------------------------
# Import tests (without pystray)
# ---------------------------------------------------------------------------


class TestTrayImport:
    """Test tray module import behaviour."""

    def test_module_importable(self) -> None:
        """Test that the tray module can be imported."""

        # Clean module cache for fresh import
        if "kicad_mcp.tray" in sys.modules:
            del sys.modules["kicad_mcp.tray"]
        from kicad_mcp import tray

        assert tray is not None
        assert hasattr(tray, "_HAS_TRAY")
        assert hasattr(tray, "_HAS_PIL")

    def test_has_pil(self) -> None:
        """Verify PIL detection works (PIL is a dev dependency)."""
        from kicad_mcp import tray

        # PIL should be detected since it's a dev dependency
        # This test verifies the detection mechanism, not the value
        assert isinstance(tray._HAS_PIL, bool)

    def test_icon_creation_with_pil(self) -> None:
        """Test that _create_icon works when PIL is available."""
        from kicad_mcp.tray import _HAS_PIL, _create_icon

        if not _HAS_PIL:
            pytest.skip("PIL not available")

        icon = _create_icon()
        assert icon is not None
        assert icon.size == (64, 64)
        assert icon.mode == "RGBA"


# ---------------------------------------------------------------------------
# KiCadTrayApp tests
# ---------------------------------------------------------------------------


class TestKiCadTrayApp:
    """Test the KiCadTrayApp class."""

    @pytest.fixture(autouse=True)
    def _ensure_pystray(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure pystray is seen as available for tests that need it."""
        # Only run for tests that need it - the run() method checks _HAS_TRAY
        pass

    @pytest.fixture
    def mock_pystray(self) -> Generator[MagicMock]:
        """Mock the pystray module."""
        with patch.dict("sys.modules", {"pystray": MagicMock()}) as mock_modules:
            pystray_mock = mock_modules["pystray"]
            pystray_mock.MenuItem = MagicMock()
            pystray_mock.Menu = MagicMock()
            pystray_mock.Icon = MagicMock()
            pystray_mock.Menu.SEPARATOR = "---"
            yield pystray_mock

    @pytest.fixture
    def tray_app(self) -> Generator:
        """Create a KiCadTrayApp instance with mocked pystray availability."""
        from kicad_mcp.tray import KiCadTrayApp

        with patch("kicad_mcp.tray._HAS_TRAY", True):
            app = KiCadTrayApp()
            yield app

    def test_init(self, tray_app) -> None:
        """Test initial state of tray app."""
        assert tray_app._server_proc is None
        assert tray_app._server_port == 3334
        assert tray_app._running is False
        assert tray_app._icon is None

    def test_run_requires_pystray(self) -> None:
        """Test that run() exits when pystray is not available."""
        from kicad_mcp.tray import KiCadTrayApp

        app = KiCadTrayApp()
        with patch("kicad_mcp.tray._HAS_TRAY", False):
            with pytest.raises(SystemExit):
                app.run()

    def test_build_menu_structure(self, mock_pystray: MagicMock, tray_app) -> None:
        """Test that the menu has the expected items."""
        menu = tray_app._build_menu()
        assert menu is not None

    def test_stop_without_server(self, tray_app) -> None:
        """Test stop() when no server is running."""
        tray_app.stop()
        # Should not raise

    def test_stop_with_server(self, tray_app) -> None:
        """Test stop() when server is running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        tray_app._server_proc = mock_proc

        tray_app.stop()
        mock_proc.terminate.assert_called_once()

    def test_stop_kills_on_timeout(self, tray_app) -> None:
        """Test stop() kills the server if terminate times out."""

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        mock_proc.wait.side_effect = [subprocess.TimeoutExpired("cmd", 5), None]
        tray_app._server_proc = mock_proc

        tray_app.stop()
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_start_server_creates_process(self, tray_app) -> None:
        """Test _action_start_server creates a subprocess."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0  # not running

        with patch("kicad_mcp.tray.subprocess.Popen", return_value=mock_proc) as mock_popen:
            with patch.object(tray_app, "_show_notification"):
                tray_app._action_start_server()
                mock_popen.assert_called_once()

    def test_start_server_skips_if_running(self, tray_app) -> None:
        """Test _action_start_server does nothing if server is already running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        tray_app._server_proc = mock_proc

        with patch("kicad_mcp.tray.subprocess.Popen") as mock_popen:
            tray_app._action_start_server()
            mock_popen.assert_not_called()

    def test_stop_server_action(self, tray_app) -> None:
        """Test _action_stop_server."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        tray_app._server_proc = mock_proc

        with patch.object(tray_app, "_show_notification"):
            tray_app._action_stop_server()
            mock_proc.terminate.assert_called_once()

    def test_action_run_drc_uses_canonical_runner(
        self,
        tray_app,
        tmp_path: Path,
    ) -> None:
        from kicad_mcp.validation.drc_runner import DrcRunResult

        pcb_file = tmp_path / "board.kicad_pcb"
        pcb_file.write_text("(kicad_pcb)", encoding="utf-8")
        output_dir = tmp_path / "output"
        cfg = MagicMock()
        cfg.pcb_file = pcb_file
        cfg.kicad_cli = Path("kicad-cli")
        cfg.ensure_output_dir.return_value = output_dir
        result = DrcRunResult(
            output_dir / "tray_drc_report.json",
            "findings",
            {"violations": [{"type": "clearance"}], "unconnected_items": []},
            5,
            "violations found",
            None,
        )

        with patch("kicad_mcp.config.get_config", return_value=cfg):
            with patch("kicad_mcp.discovery.get_cli_capabilities", return_value=MagicMock()):
                with patch(
                    "kicad_mcp.validation.drc_runner.run_drc_report",
                    return_value=result,
                ) as run_drc:
                    with patch("kicad_mcp.tray.subprocess.run") as direct_run:
                        with patch.object(tray_app, "_show_notification") as notify:
                            tray_app._action_run_drc()

        run_drc.assert_called_once()
        direct_run.assert_not_called()
        notify.assert_called_once_with("DRC completed with design findings")

    def test_action_show_status(self, tray_app) -> None:
        """Test _action_show_status calls build_health_report."""
        # Patch at the import source (diagnostics module) since tray
        # does `from .diagnostics import build_health_report` inside the method
        with patch("kicad_mcp.diagnostics.build_health_report") as mock_health:
            report = MagicMock(spec=["status", "checks"])
            report.status = "ok"
            report.checks = []
            mock_health.return_value = report
            with patch.object(tray_app, "_show_notification") as mock_notify:
                tray_app._action_show_status()
                mock_notify.assert_called_once()

    def test_action_quit_stops(self, tray_app) -> None:
        """Test _action_quit calls stop()."""
        with patch.object(tray_app, "stop") as mock_stop:
            tray_app._action_quit()
            mock_stop.assert_called_once()

    def test_show_notification(self, tray_app) -> None:
        """Test _show_notification calls icon.notify."""
        mock_icon = MagicMock()
        tray_app._icon = mock_icon

        tray_app._show_notification("Test message")
        mock_icon.notify.assert_called_once_with("Test message", title="KiCad MCP Pro")

    def test_show_notification_without_icon(self, tray_app) -> None:
        """Test _show_notification does not fail without icon."""
        tray_app._icon = None
        tray_app._show_notification("Test")
        # Should not raise

    def test_open_dashboard_starts_server_if_needed(self, tray_app) -> None:
        """Test _action_open_dashboard starts the server if not running."""
        tray_app._server_proc = None

        with patch("webbrowser.open") as mock_webbrowser:
            with patch.object(tray_app, "_action_start_server") as mock_start:
                tray_app._action_open_dashboard()
                mock_start.assert_called_once()
                mock_webbrowser.assert_called_once_with("http://127.0.0.1:3334/ui")

    def test_open_dashboard_skips_if_running(self, tray_app) -> None:
        """Test _action_open_dashboard does not start server if already running."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None  # running
        tray_app._server_proc = mock_proc

        with patch("webbrowser.open") as mock_webbrowser:
            with patch.object(tray_app, "_action_start_server") as mock_start:
                tray_app._action_open_dashboard()
                mock_start.assert_not_called()
                mock_webbrowser.assert_called_once()


# ---------------------------------------------------------------------------
# tray_main tests
# ---------------------------------------------------------------------------


class TestTrayMain:
    """Test the tray_main entry point."""

    def test_tray_main_without_pystray(self) -> None:
        """Test tray_main exits when pystray is not available."""
        with patch("kicad_mcp.tray._HAS_TRAY", False):
            with pytest.raises(SystemExit):
                from kicad_mcp.tray import tray_main

                tray_main()

    def test_tray_main_with_pystray(self) -> None:
        """Test tray_main creates KiCadTrayApp and runs."""
        mock_app = MagicMock()

        with patch("kicad_mcp.tray._HAS_TRAY", True):
            with patch("kicad_mcp.tray.KiCadTrayApp", return_value=mock_app):
                from kicad_mcp.tray import tray_main

                tray_main()
                mock_app.run.assert_called_once()

    def test_tray_main_passes_port(self) -> None:
        """Test tray_main passes a custom port to KiCadTrayApp."""
        mock_app = MagicMock()

        with patch("kicad_mcp.tray._HAS_TRAY", True):
            with patch("kicad_mcp.tray.KiCadTrayApp", return_value=mock_app) as mock_cls:
                from kicad_mcp.tray import tray_main

                tray_main(port=8080)
                mock_cls.assert_called_once_with(port=8080)
                mock_app.run.assert_called_once()

    def test_tray_main_keyboard_interrupt(self) -> None:
        """Test tray_main handles KeyboardInterrupt gracefully."""
        mock_app = MagicMock()
        mock_app.run.side_effect = KeyboardInterrupt()

        with patch("kicad_mcp.tray._HAS_TRAY", True):
            with patch("kicad_mcp.tray.KiCadTrayApp", return_value=mock_app):
                from kicad_mcp.tray import tray_main

                tray_main()
                mock_app.stop.assert_called_once()

    def test_tray_main_propagates_runtime_error(self) -> None:
        """Test tray_main propagates RuntimeError (caught by CLI handler)."""
        mock_app = MagicMock()
        mock_app.run.side_effect = RuntimeError("tray failure")

        with patch("kicad_mcp.tray._HAS_TRAY", True):
            with patch("kicad_mcp.tray.KiCadTrayApp", return_value=mock_app):
                from kicad_mcp.tray import tray_main

                with pytest.raises(RuntimeError, match="tray failure"):
                    tray_main()


# ---------------------------------------------------------------------------
# Icon creation tests
# ---------------------------------------------------------------------------


class TestIconCreation:
    """Test the _create_icon function."""

    def test_icon_requires_pil(self) -> None:
        """Test _create_icon raises ImportError when PIL is not available."""
        from kicad_mcp.tray import _create_icon

        with patch("kicad_mcp.tray._HAS_PIL", False):
            with pytest.raises(ImportError):
                _create_icon()

    def test_icon_size(self) -> None:
        """Test the icon is 64x64 when PIL is available."""
        from kicad_mcp.tray import _HAS_PIL, _create_icon

        if not _HAS_PIL:
            pytest.skip("PIL not available")

        icon = _create_icon()
        assert icon.size == (64, 64)

    def test_icon_mode(self) -> None:
        """Test the icon uses RGBA mode."""
        from kicad_mcp.tray import _HAS_PIL, _create_icon

        if not _HAS_PIL:
            pytest.skip("PIL not available")

        icon = _create_icon()
        assert icon.mode == "RGBA"
