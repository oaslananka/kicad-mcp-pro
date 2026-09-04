"""Tests for the web dashboard, API routes, and SSE log streaming."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from kicad_mcp import __version__  # noqa: E402  (after sys.path bootstrap above)

if TYPE_CHECKING:
    from collections.abc import Generator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset globals between tests."""
    from kicad_mcp.config import reset_config

    monkeypatch.delenv("KICAD_MCP_HOST", raising=False)
    monkeypatch.delenv("KICAD_MCP_PORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_CORS_ORIGINS", raising=False)
    reset_config()


@pytest.fixture
def mock_health_report() -> Generator[MagicMock]:
    """Mock build_health_report to return predictable data."""
    with patch("kicad_mcp.web.routes.build_health_report") as mock:
        report = MagicMock(spec_set=["ok", "status", "checks"])
        report.ok = True
        report.status = "ok"
        check1 = MagicMock(spec_set=["name", "status", "message"])
        check1.name = "KiCad CLI"
        check1.status = "ok"
        check1.message = "found"
        check2 = MagicMock(spec_set=["name", "status", "message"])
        check2.name = "kicad-cli check"
        check2.status = "ok"
        check2.message = "10.0"
        report.checks = [check1, check2]
        mock.return_value = report
        yield mock


@pytest.fixture
def mock_ipc_state() -> Generator[MagicMock]:
    """Mock IPC capability state."""
    with patch("kicad_mcp.web.routes.get_ipc_capability_state") as mock:
        state = MagicMock()
        state.reachable = False
        mock.return_value = state
        yield mock


@pytest.fixture
def mock_kicad_version() -> Generator[MagicMock]:
    """Mock find_kicad_version."""
    with patch("kicad_mcp.web.routes.find_kicad_version") as mock:
        mock.return_value = "10.0.1"
        yield mock


# ---------------------------------------------------------------------------
# Import & module tests
# ---------------------------------------------------------------------------


class TestWebModule:
    """Test that the web module imports and its exports are correct."""

    def test_import_web_module(self) -> None:
        """Verify web module can be imported and has expected exports."""
        from kicad_mcp.web import router, setup_log_stream

        assert router is not None
        assert callable(setup_log_stream)

    def test_routes_list(self) -> None:
        """Verify web_routes contains expected routes."""
        from kicad_mcp.web.routes import web_routes

        assert len(web_routes) >= 5
        paths = {r.path for r in web_routes}
        assert "/api/status" in paths
        assert "/api/health" in paths
        assert "/api/info" in paths
        assert "/api/logs/stream" in paths
        assert "/ui" in paths
        assert "/api/dashboard" in paths
        assert "/" in paths

    def test_dashboard_html_content(self) -> None:
        """Verify dashboard HTML is non-empty and contains key elements."""
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert len(DASHBOARD_HTML) > 1000
        assert "KiCad MCP Pro Dashboard" in DASHBOARD_HTML
        assert "Log Viewer" in DASHBOARD_HTML
        assert "refreshStatus" in DASHBOARD_HTML
        assert "connectSSE" in DASHBOARD_HTML
        assert "setLogFilter" in DASHBOARD_HTML
        assert __version__ in DASHBOARD_HTML


# ---------------------------------------------------------------------------
# SSE log stream tests
# ---------------------------------------------------------------------------


class TestSSELogStream:
    """Test the SSE log broadcast and subscription mechanism."""

    @pytest.mark.anyio
    async def test_broadcast_and_receive(self) -> None:
        """Test that log entries are broadcast to subscribers and received."""
        from kicad_mcp.web.routes import _broadcast_log, _log_subscribers

        # Ensure clean state
        _log_subscribers.clear()

        q: asyncio.Queue = asyncio.Queue()
        _log_subscribers.append(q)

        test_entry = json.dumps({"level": "INFO", "event": "test message"})
        await _broadcast_log(test_entry)

        received = await asyncio.wait_for(q.get(), timeout=2.0)
        assert received == test_entry

    @pytest.mark.anyio
    async def test_subscriber_removed_on_full_queue(self) -> None:
        """Test that dead subscribers are cleaned up when queue is full."""
        from kicad_mcp.web.routes import _broadcast_log, _log_subscribers

        _log_subscribers.clear()

        # Create a queue with maxsize=1 and fill it
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        q.put_nowait("full")
        _log_subscribers.append(q)

        await _broadcast_log("new entry")
        assert q not in _log_subscribers

    @pytest.mark.anyio
    async def test_sse_generator_yields_connected(self) -> None:
        """Test that the SSE generator yields a 'connected' event first."""
        from kicad_mcp.web.routes import _log_subscribers, _sse_log_generator

        _log_subscribers.clear()

        gen = _sse_log_generator()
        first = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert "connected" in first

        # Clean shutdown
        await gen.aclose()

    @pytest.mark.anyio
    async def test_sse_generator_receives_logs(self) -> None:
        """Test that the SSE generator yields broadcast log entries."""
        from kicad_mcp.web.routes import _broadcast_log, _log_subscribers, _sse_log_generator

        _log_subscribers.clear()

        gen = _sse_log_generator()
        await asyncio.wait_for(gen.__anext__(), timeout=2.0)  # connected

        test_entry = json.dumps({"level": "INFO", "event": "sse test"})
        await _broadcast_log(test_entry)

        second = await asyncio.wait_for(gen.__anext__(), timeout=2.0)
        assert "sse test" in second

        await gen.aclose()

    @pytest.mark.anyio
    async def test_sse_generator_cleanup_on_cancel(self) -> None:
        """Test that the SSE generator removes its queue on cancellation."""
        from kicad_mcp.web.routes import _log_subscribers, _sse_log_generator

        _log_subscribers.clear()
        initial_count = len(_log_subscribers)

        gen = _sse_log_generator()
        await asyncio.wait_for(gen.__anext__(), timeout=2.0)  # connected
        assert len(_log_subscribers) == initial_count + 1

        await gen.aclose()
        assert len(_log_subscribers) == initial_count

    def test_push_log_thread_safe(self) -> None:
        """Test that push_log can be called without a running event loop."""
        from kicad_mcp.web.routes import push_log

        # This should not raise even without a running loop
        push_log("INFO", "test from non-async context")

    @pytest.mark.anyio
    async def test_push_log_with_loop(self) -> None:
        """Test that push_log works when an event loop is running."""
        from kicad_mcp.web.routes import push_log

        push_log("INFO", "push test")
        # No exception expected

    def test_setup_log_stream_configures_structlog(self) -> None:
        """Test that setup_log_stream runs without error."""
        from kicad_mcp.web.routes import setup_log_stream

        with patch("kicad_mcp.web.routes.structlog.configure") as mock_configure:
            setup_log_stream()
            mock_configure.assert_called_once()


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    """Test the API endpoint handlers."""

    @pytest.mark.anyio
    async def test_api_status(
        self,
        mock_health_report: MagicMock,
        mock_ipc_state: MagicMock,
        mock_kicad_version: MagicMock,
    ) -> None:
        """Test /api/status returns expected JSON structure."""
        from kicad_mcp.web.routes import api_status

        request = MagicMock()
        response = await api_status(request)
        data = json.loads(response.body)

        assert data["server"]["version"] == __version__
        assert data["health"]["ok"] is True
        assert data["health"]["status"] == "ok"
        assert "kicad" in data
        assert "project" in data
        assert "tools" in data
        # Regression guard: this is the public tool count, not the number of
        # enabled categories for the active profile.
        assert data["tools"]["active_tool_count"] == 24
        assert "timestamp" in data

    @pytest.mark.anyio
    async def test_api_health(self, mock_health_report: MagicMock) -> None:
        """Test /api/health returns lightweight health check."""
        from kicad_mcp.web.routes import api_health

        request = MagicMock()
        response = await api_health(request)
        data = json.loads(response.body)

        assert data["ok"] is True
        assert data["status"] == "ok"
        assert data["version"] == __version__
        assert data["desktopCompatibility"] == {
            "contractVersion": "1.0.0",
            "backendVersion": __version__,
            "versionPolicy": "exact-release",
        }
        assert "uptime" in data

    @pytest.mark.anyio
    async def test_api_info(self) -> None:
        """Test /api/info returns server information."""
        from kicad_mcp.web.routes import api_info

        request = MagicMock()
        response = await api_info(request)
        data = json.loads(response.body)

        assert data["name"] == "KiCad MCP Pro"
        assert data["version"] == __version__
        assert "python" in data
        assert "platform" in data
        assert "config" in data

    @pytest.mark.anyio
    async def test_api_log_stream_headers(self) -> None:
        """Test SSE endpoint returns proper streaming response headers."""
        from kicad_mcp.web.routes import api_log_stream

        request = MagicMock()
        response = await api_log_stream(request)

        assert response.media_type == "text/event-stream"
        assert response.headers.get("Cache-Control") == "no-cache"
        assert response.headers.get("X-Accel-Buffering") == "no"

    @pytest.mark.anyio
    async def test_api_dashboard_html(self) -> None:
        """Test /api/dashboard returns HTML."""
        from kicad_mcp.web.routes import api_dashboard

        request = MagicMock()
        response = await api_dashboard(request)

        assert "KiCad MCP Pro Dashboard" in response.body.decode()
        assert response.media_type == "text/html"


# ---------------------------------------------------------------------------
# Dashboard HTML tests
# ---------------------------------------------------------------------------


class TestDashboardHTML:
    """Test the dashboard HTML content."""

    def test_dashboard_has_status_dot(self) -> None:
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert 'id="navStatusDot"' in DASHBOARD_HTML

    def test_dashboard_has_log_container(self) -> None:
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert 'id="log-container"' in DASHBOARD_HTML

    def test_dashboard_has_health_checks(self) -> None:
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert 'id="health-checks"' in DASHBOARD_HTML

    def test_dashboard_has_quick_actions(self) -> None:
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert "Quick Actions" in DASHBOARD_HTML
        assert "Refresh Status" in DASHBOARD_HTML

    def test_dashboard_version_replaced(self) -> None:
        """Verify template placeholder was replaced on import."""
        from kicad_mcp.web.dashboard import DASHBOARD_HTML

        assert "{{version}}" not in DASHBOARD_HTML
        assert __version__ in DASHBOARD_HTML


# ---------------------------------------------------------------------------
# Integration-ish: route registration with Starlette TestClient
# ---------------------------------------------------------------------------


class TestRouteRegistration:
    """Test that web_routes can be served via Starlette TestClient."""

    def test_web_routes_list_asgi_ready(self) -> None:
        """Verify that the web_routes list can create a Starlette app."""
        from starlette.applications import Starlette

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        assert len(app.routes) == len(web_routes)

    def test_status_via_test_client(self, mock_health_report: MagicMock) -> None:
        """Test that /api/status responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["server"]["version"] == __version__

    def test_health_via_test_client(self) -> None:
        """Test that /api/health responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/health")
        assert response.status_code == 200

    def test_info_via_test_client(self) -> None:
        """Test that /api/info responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/info")
        assert response.status_code == 200

    def test_dashboard_via_test_client(self) -> None:
        """Test that /api/dashboard responds with HTML."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/dashboard")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_root_serves_dashboard(self) -> None:
        """Test that / serves the dashboard HTML."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/")
        assert response.status_code == 200
        assert "KiCad MCP Pro Dashboard" in response.text

    def test_ui_serves_dashboard(self) -> None:
        """Test that /ui serves the dashboard HTML."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/ui")
        assert response.status_code == 200
        assert "KiCad MCP Pro Dashboard" in response.text


@pytest.mark.anyio
async def test_api_health_reports_runtime_capability_without_sensitive_diagnostics(
    mock_health_report: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion health can fail closed when KiCad IPC/runtime is unavailable."""
    from types import SimpleNamespace

    from kicad_mcp.web.routes import api_health

    monkeypatch.setattr(
        "kicad_mcp.web.routes.get_ipc_capability_state",
        lambda: SimpleNamespace(
            reachable=False,
            live_pcb_context=False,
            live_schematic_context=False,
            headless_ipc_available=False,
        ),
    )

    response = await api_health(MagicMock())
    data = json.loads(response.body)

    assert data["kicadRuntime"] == {
        "available": False,
        "ipcReachable": False,
        "livePcbContext": False,
        "liveSchematicContext": False,
        "headless": False,
    }
    assert "diagnostics" not in data["kicadRuntime"]


@pytest.mark.anyio
async def test_sse_generator_propagates_cancellation() -> None:
    from kicad_mcp.web.routes import _log_subscribers, _sse_log_generator

    _log_subscribers.clear()
    gen = _sse_log_generator()
    await gen.__anext__()
    assert len(_log_subscribers) == 1

    pending = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert _log_subscribers == []
