"""Tests for Step 3 API endpoints: tools, config, config/export, metrics, server control.

These cover the 6 new endpoints added in Step 3 of the GUI spec.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src is importable
SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset config and state globals between tests."""
    from kicad_mcp.config import reset_config
    from kicad_mcp.web.state import reset_metrics, set_server_handle

    monkeypatch.delenv("KICAD_MCP_HOST", raising=False)
    monkeypatch.delenv("KICAD_MCP_PORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_TRANSPORT", raising=False)
    monkeypatch.delenv("KICAD_MCP_CORS_ORIGINS", raising=False)
    reset_config()
    # Reset server handle and metrics to prevent cross-test pollution
    set_server_handle(None)
    reset_metrics()


# ---------------------------------------------------------------------------
# state.py tests
# ---------------------------------------------------------------------------


class TestStateModule:
    """Test the shared state module."""

    def test_import_state(self) -> None:
        """Verify state module imports."""
        from kicad_mcp.web.state import (
            _TOOL_CALL_COUNTS,
            _TOOL_LATENCIES_MS,
            get_server_handle,
            get_start_time,
            reset_start_time,
            set_server_handle,
        )

        assert callable(set_server_handle)
        assert callable(get_server_handle)
        assert callable(reset_start_time)
        assert callable(get_start_time)
        assert isinstance(_TOOL_CALL_COUNTS, dict)
        assert isinstance(_TOOL_LATENCIES_MS, dict)

    def test_server_handle_roundtrip(self) -> None:
        """Test set/get server handle."""
        from kicad_mcp.web.state import get_server_handle, set_server_handle

        set_server_handle(None)
        assert get_server_handle() is None

        handle = MagicMock()
        set_server_handle(handle)
        assert get_server_handle() is handle

    def test_start_time_roundtrip(self) -> None:
        """Test reset/get start time."""
        from kicad_mcp.web.state import get_start_time, reset_start_time

        before = get_start_time()
        assert before > 0

        reset_start_time()
        after = get_start_time()
        assert after >= before

    def test_metrics_snapshot_empty(self) -> None:
        """Test get_metrics_snapshot with no recorded calls."""
        from kicad_mcp.web.state import get_metrics_snapshot

        snap = get_metrics_snapshot()
        assert snap["call_counts"] == {}
        assert snap["total_calls"] == 0
        assert snap["total_errors"] == 0

    def test_metrics_snapshot_with_data(self) -> None:
        """Test get_metrics_snapshot with recorded tool calls."""
        from kicad_mcp.web.state import (
            _METRICS_LOCK,
            _TOOL_CALL_COUNTS,
            _TOOL_LATENCIES_MS,
            get_metrics_snapshot,
        )

        with _METRICS_LOCK:
            _TOOL_CALL_COUNTS.clear()
            _TOOL_LATENCIES_MS.clear()
            _TOOL_CALL_COUNTS[("place_footprint", "ok")] = 5
            _TOOL_CALL_COUNTS[("place_footprint", "error")] = 1
            _TOOL_CALL_COUNTS[("route_trace", "ok")] = 10
            _TOOL_LATENCIES_MS["place_footprint"] = [10.0, 20.0, 30.0]
            _TOOL_LATENCIES_MS["route_trace"] = [5.0, 15.0]

        try:
            snap = get_metrics_snapshot()
            assert snap["call_counts"]["place_footprint"]["ok"] == 5
            assert snap["call_counts"]["place_footprint"]["error"] == 1
            assert snap["call_counts"]["route_trace"]["ok"] == 10
            assert snap["total_calls"] == 16
            assert snap["total_errors"] == 1
            assert "latencies_ms" in snap
            pf_lat = snap["latencies_ms"]["place_footprint"]
            assert pf_lat["count"] == 3
            assert pf_lat["min"] == 10.0
            assert pf_lat["max"] == 30.0
        finally:
            with _METRICS_LOCK:
                _TOOL_CALL_COUNTS.clear()
                _TOOL_LATENCIES_MS.clear()

    def test_metrics_snapshot_empty_latencies(self) -> None:
        """Test get_metrics_snapshot with calls but no latencies."""
        from kicad_mcp.web.state import (
            _METRICS_LOCK,
            _TOOL_CALL_COUNTS,
            _TOOL_LATENCIES_MS,
            get_metrics_snapshot,
        )

        with _METRICS_LOCK:
            _TOOL_CALL_COUNTS.clear()
            _TOOL_LATENCIES_MS.clear()
            _TOOL_CALL_COUNTS[("some_tool", "ok")] = 3

        try:
            snap = get_metrics_snapshot()
            assert snap["call_counts"]["some_tool"]["ok"] == 3
            # no latencies entry since _TOOL_LATENCIES_MS is empty
            assert snap["total_calls"] == 3
            assert snap["total_errors"] == 0
        finally:
            with _METRICS_LOCK:
                _TOOL_CALL_COUNTS.clear()
                _TOOL_LATENCIES_MS.clear()


class TestPercentile:
    """Test the _percentile_from_sorted helper."""

    def test_empty(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        assert _percentile_from_sorted([], 0.5) == 0.0

    def test_single_value(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        assert _percentile_from_sorted([42.0], 0.5) == 42.0

    def test_p50(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        assert _percentile_from_sorted([1.0, 2.0, 3.0], 0.50) == 2.0

    def test_p95(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        samples = [float(i) for i in range(100)]
        result = _percentile_from_sorted(samples, 0.95)
        assert result == 94.0  # index 94

    def test_p99(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        samples = [float(i) for i in range(100)]
        result = _percentile_from_sorted(samples, 0.99)
        # int(round((100-1) * 0.99)) = int(round(98.01)) = 98
        assert result == 98.0

    def test_clamp_low(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        assert _percentile_from_sorted([5.0], 0.0) == 5.0

    def test_clamp_high(self) -> None:
        from kicad_mcp.web.state import _percentile_from_sorted

        assert _percentile_from_sorted([5.0], 1.0) == 5.0


# ---------------------------------------------------------------------------
# Step 3 API endpoint tests
# ---------------------------------------------------------------------------


class TestAPITools:
    """Test GET /api/tools."""

    @pytest.mark.anyio
    async def test_tools_no_handle(self) -> None:
        """Returns 503 when server handle is not initialized."""
        from kicad_mcp.web.routes import api_tools

        with patch("kicad_mcp.web.routes.get_server_handle", return_value=None):
            request = MagicMock()
            response = await api_tools(request)
            data = json.loads(response.body)
            assert response.status_code == 503
            assert "error" in data
            assert data["tools"] == []

    @pytest.mark.anyio
    async def test_tools_empty(self) -> None:
        """Returns empty tools list when server has no tools."""
        from kicad_mcp.web.routes import api_tools

        handle = MagicMock()
        handle.list_tools.return_value = []
        with patch("kicad_mcp.web.routes.get_server_handle", return_value=handle):
            request = MagicMock()
            response = await api_tools(request)
            data = json.loads(response.body)
            assert response.status_code == 200
            assert data["count"] == 0
            assert data["tools"] == []

    @pytest.mark.anyio
    async def test_tools_with_model_dump(self) -> None:
        """Returns tools with metadata when tools have model_dump."""
        from kicad_mcp.web.routes import api_tools

        mock_tool = MagicMock()
        mock_tool.model_dump.return_value = {
            "name": "place_footprint",
            "description": "Place a footprint",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {},
        }

        handle = MagicMock()
        handle.list_tools.return_value = [mock_tool]
        with patch("kicad_mcp.web.routes.get_server_handle", return_value=handle):
            request = MagicMock()
            response = await api_tools(request)
            data = json.loads(response.body)
            assert response.status_code == 200
            assert data["count"] == 1
            assert data["tools"][0]["name"] == "place_footprint"
            assert data["tools"][0]["description"] == "Place a footprint"

    @pytest.mark.anyio
    async def test_tools_fallback_no_model_dump(self) -> None:
        """Returns name-only when tool has no model_dump."""
        from kicad_mcp.web.routes import api_tools

        # Create a mock that has no model_dump attribute
        # Use object spec so __str__ returns the default object repr
        mock_tool = MagicMock(spec=object)
        if hasattr(mock_tool, "model_dump"):
            del mock_tool.model_dump

        # Override __str__ via the type
        type(mock_tool).__str__ = lambda self: "fallback_tool"  # type: ignore[method-assign]

        handle = MagicMock()
        handle.list_tools.return_value = [mock_tool]
        with patch("kicad_mcp.web.routes.get_server_handle", return_value=handle):
            request = MagicMock()
            response = await api_tools(request)
            data = json.loads(response.body)
            assert response.status_code == 200
            assert data["count"] == 1
            # Fallback: name = str(tool)
            assert data["tools"][0]["name"] == "fallback_tool"

    @pytest.mark.anyio
    async def test_tools_handle_raises(self) -> None:
        """Returns 500 when list_tools raises."""
        from kicad_mcp.web.routes import api_tools

        handle = MagicMock()
        handle.list_tools.side_effect = RuntimeError("boom")
        with patch("kicad_mcp.web.routes.get_server_handle", return_value=handle):
            request = MagicMock()
            response = await api_tools(request)
            data = json.loads(response.body)
            assert response.status_code == 500
            assert "error" in data
            assert data["tools"] == []


class TestAPIConfig:
    """Test GET and POST /api/config."""

    @pytest.mark.anyio
    async def test_config_get(self) -> None:
        """Returns current config."""
        from kicad_mcp.web.routes import api_config_get

        request = MagicMock()
        response = await api_config_get(request)
        data = json.loads(response.body)
        assert "config" in data
        assert isinstance(data["config"], dict)

    @pytest.mark.anyio
    async def test_config_get_includes_operating_mode(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GET /api/config exposes the active operating mode for the dashboard dropdown."""
        from kicad_mcp.config import reset_config
        from kicad_mcp.web.routes import api_config_get

        monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
        reset_config()
        request = MagicMock()
        response = await api_config_get(request)
        data = json.loads(response.body)
        assert data["config"]["operating_mode"] == "write"
        assert data["operating_mode"] == "write"

    @pytest.mark.anyio
    async def test_config_post_no_body(self) -> None:
        """Returns 400 for non-JSON body."""
        from kicad_mcp.web.routes import api_config_post

        request = MagicMock()

        async def _raise(*args: object) -> object:
            raise ValueError("Not JSON")

        request.json = _raise
        response = await api_config_post(request)
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.anyio
    async def test_config_post_non_dict(self) -> None:
        """Returns 400 for non-dict body."""
        from kicad_mcp.web.routes import api_config_post

        request = MagicMock()

        async def _return_list() -> list[str]:
            return ["not", "a", "dict"]

        request.json = _return_list
        response = await api_config_post(request)
        assert response.status_code == 400

    @pytest.mark.anyio
    async def test_config_post_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Applies env vars and returns updated config."""
        from kicad_mcp.web.routes import api_config_post

        monkeypatch.setenv("KICAD_MCP_HOST", "0.0.0.0")  # noqa: S104
        monkeypatch.setenv("KICAD_MCP_PORT", "8765")

        request = MagicMock()

        async def _return_body() -> dict[str, str]:
            return {"host": "127.0.0.1", "port": "9090"}

        request.json = _return_body
        response = await api_config_post(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert "applied" in data
        assert data["errors"] == []
        assert "host" in data["applied"]
        assert "port" in data["applied"]

    @pytest.mark.anyio
    async def test_config_post_empty(self) -> None:
        """Empty body returns applied=[], errors=[]."""
        from kicad_mcp.web.routes import api_config_post

        request = MagicMock()

        async def _return_empty() -> dict[str, str]:
            return {}

        request.json = _return_empty
        response = await api_config_post(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["applied"] == []


class TestAPIConfigExport:
    """Test GET /api/config/export/{client}."""

    @pytest.mark.anyio
    async def test_export_invalid_client(self) -> None:
        """Returns 400 for unknown client."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "nonexistent"}
        response = await api_config_export(request)
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.anyio
    async def test_export_claude(self) -> None:
        """Export for claude returns stdio JSON."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "claude"}
        response = await api_config_export(request)
        data = json.loads(response.body)
        assert data["client"] == "claude-desktop"
        assert data["format"] == "json"
        assert "kicad-mcp-pro" in data["config"]
        assert "snippet" in data
        assert "config_path" in data

    @pytest.mark.anyio
    async def test_export_cursor(self) -> None:
        """Export for cursor returns stdio JSON."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "cursor"}
        response = await api_config_export(request)
        data = json.loads(response.body)
        assert data["client"] == "cursor"
        assert "command" in data["config"]

    @pytest.mark.anyio
    async def test_export_vscode(self) -> None:
        """Export for vscode returns JSON with type: stdio."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "vscode"}
        response = await api_config_export(request)
        data = json.loads(response.body)
        assert data["client"] == "vscode"
        assert data["format"] == "json"
        assert "servers" in data["config"]

    @pytest.mark.anyio
    async def test_export_codex(self) -> None:
        """Export for codex returns TOML-like format."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "codex"}
        response = await api_config_export(request)
        data = json.loads(response.body)
        assert data["client"] == "codex"
        assert data["format"] == "toml"
        assert "mcp_servers" in data["config"]

    @pytest.mark.anyio
    async def test_export_case_insensitive(self) -> None:
        """Client name is case-insensitive."""
        from kicad_mcp.web.routes import api_config_export

        request = MagicMock()
        request.path_params = {"client": "CLAUDE"}
        response = await api_config_export(request)
        assert response.status_code == 200
        data = json.loads(response.body)
        assert data["client"] == "claude-desktop"

    @pytest.mark.anyio
    async def test_export_all_spec_clients(self) -> None:
        """All dashboard-supported MCP clients export snippets."""
        from kicad_mcp.web.routes import api_config_export

        for client in ["claude-desktop", "cursor", "vscode", "windsurf", "zed"]:
            request = MagicMock()
            request.path_params = {"client": client}
            response = await api_config_export(request)
            data = json.loads(response.body)
            assert response.status_code == 200
            assert data["client"] == client
            assert data["config_path"]
            assert "kicad-mcp-pro" in data["config"]


class TestAPIMetrics:
    """Test GET /api/metrics."""

    @pytest.mark.anyio
    async def test_metrics_empty(self) -> None:
        """Returns empty metrics when no calls have been made."""
        from kicad_mcp.web.routes import api_metrics

        with patch(
            "kicad_mcp.web.routes.get_metrics_snapshot",
            return_value={
                "call_counts": {},
                "latencies_ms": {},
                "total_calls": 0,
                "total_errors": 0,
            },
        ):
            request = MagicMock()
            response = await api_metrics(request)
            data = json.loads(response.body)
            assert data["total_calls"] == 0
            assert data["total_errors"] == 0
            assert data["call_counts"] == {}
            assert "uptime_seconds" in data
            assert "uptime_human" in data
            assert data["uptime_seconds"] >= 0

    @pytest.mark.anyio
    async def test_metrics_with_data(self) -> None:
        """Returns metrics snapshot with data."""
        from kicad_mcp.web.routes import api_metrics

        with patch(
            "kicad_mcp.web.routes.get_metrics_snapshot",
            return_value={
                "call_counts": {"place_footprint": {"ok": 5, "error": 1}},
                "latencies_ms": {},
                "total_calls": 6,
                "total_errors": 1,
            },
        ):
            request = MagicMock()
            response = await api_metrics(request)
            data = json.loads(response.body)
            assert data["total_calls"] == 6
            assert data["total_errors"] == 1
            assert data["call_counts"]["place_footprint"]["ok"] == 5


class TestAPIServerAction:
    """Test POST /api/server/{action}."""

    @pytest.mark.anyio
    async def test_unknown_action(self) -> None:
        """Returns 400 for unknown action."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "unknown"}
        response = await api_server_action(request)
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "error" in data

    @pytest.mark.anyio
    async def test_start(self) -> None:
        """Start returns running status for an already-hosted dashboard."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "start"}
        response = await api_server_action(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["action"] == "start"
        assert data["status"] == "running"

    @pytest.mark.anyio
    async def test_stop(self) -> None:
        """Stop returns initiated status."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "stop"}
        with patch("kicad_mcp.web.routes.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            response = await api_server_action(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["action"] == "stop"
        assert data["status"] == "initiated"

    @pytest.mark.anyio
    async def test_shutdown(self) -> None:
        """Shutdown returns initiated status."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "shutdown"}
        with patch("kicad_mcp.web.routes.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            response = await api_server_action(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["action"] == "shutdown"
        assert data["status"] == "initiated"

    @pytest.mark.anyio
    async def test_restart(self) -> None:
        """Restart returns initiated status."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "restart"}
        with patch("kicad_mcp.web.routes.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            response = await api_server_action(request)
        data = json.loads(response.body)
        assert response.status_code == 200
        assert data["action"] == "restart"
        assert data["status"] == "initiated"

    @pytest.mark.anyio
    async def test_action_case_insensitive(self) -> None:
        """Action name is case-insensitive."""
        from kicad_mcp.web.routes import api_server_action

        request = MagicMock()
        request.path_params = {"action": "SHUTDOWN"}
        with patch("kicad_mcp.web.routes.threading.Thread") as mock_thread:
            mock_thread.return_value.start = MagicMock()
            response = await api_server_action(request)
        assert response.status_code == 200


class TestFormatUptime:
    """Test the _format_uptime helper."""

    def test_seconds_only(self) -> None:
        from kicad_mcp.web.routes import _format_uptime

        assert _format_uptime(5) == "5s"

    def test_minutes_and_seconds(self) -> None:
        from kicad_mcp.web.routes import _format_uptime

        assert _format_uptime(125) == "2m 5s"

    def test_hours_minutes_seconds(self) -> None:
        from kicad_mcp.web.routes import _format_uptime

        assert _format_uptime(3665) == "1h 1m 5s"

    def test_days(self) -> None:
        from kicad_mcp.web.routes import _format_uptime

        assert _format_uptime(90061) == "1d 1h 1m 1s"

    def test_zero(self) -> None:
        from kicad_mcp.web.routes import _format_uptime

        assert _format_uptime(0) == "0s"


# ---------------------------------------------------------------------------
# Route registration tests for Step 3 endpoints
# ---------------------------------------------------------------------------


class TestStep3RouteRegistration:
    """Test that Step 3 routes are registered and respond via TestClient."""

    def test_step3_routes_in_web_routes(self) -> None:
        """Verify all Step 3 routes are in the route list."""
        from kicad_mcp.web.routes import web_routes

        paths = {r.path for r in web_routes}
        assert "/api/tools" in paths
        assert "/api/config" in paths  # GET and POST share the path
        assert "/api/config/export/{client}" in paths
        assert "/api/metrics" in paths
        assert "/api/server/{action}" in paths

    def test_tools_via_test_client(self) -> None:
        """Test GET /api/tools responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        # Mock get_server_handle to return None (uninitialized state)
        with patch("kicad_mcp.web.routes.get_server_handle", return_value=None):
            response = client.get("/api/tools")
            assert response.status_code == 503

    def test_config_export_via_test_client(self) -> None:
        """Test GET /api/config/export/claude responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/config/export/claude")
        assert response.status_code == 200
        data = response.json()
        assert "config" in data

    def test_config_export_invalid_via_test_client(self) -> None:
        """Test GET /api/config/export/bad returns 400."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/config/export/badclient")
        assert response.status_code == 400

    def test_metrics_via_test_client(self) -> None:
        """Test GET /api/metrics responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_calls" in data
        assert "uptime_seconds" in data

    def test_server_action_unknown_via_test_client(self) -> None:
        """Test POST /api/server/unknown returns 400."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.post("/api/server/unknown")
        assert response.status_code == 400

    def test_config_get_via_test_client(self) -> None:
        """Test GET /api/config responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert "config" in data

    def test_config_post_via_test_client(self) -> None:
        """Test POST /api/config responds via TestClient."""
        from starlette.applications import Starlette
        from starlette.testclient import TestClient

        from kicad_mcp.web.routes import web_routes

        app = Starlette(routes=web_routes)
        client = TestClient(app)

        response = client.post("/api/config", json={"host": "0.0.0.0"})  # noqa: S104
        assert response.status_code == 200
        data = response.json()
        assert "applied" in data
        assert "host" in data["applied"]
