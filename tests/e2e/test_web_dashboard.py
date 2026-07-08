"""Playwright E2E tests for the SPA dashboard.

These tests serve the embedded DASHBOARD_HTML via a stdlib HTTP server and mock
all API calls with deterministic data, allowing the SPA JavaScript to render
without a running KiCad MCP server.

Usage:
    E2E=1 pytest tests/e2e/test_web_dashboard.py --headed   # interactive
    E2E=1 pytest tests/e2e/test_web_dashboard.py              # headless (CI)
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from playwright.sync_api import Page, Route

from kicad_mcp import __version__
from kicad_mcp.web.dashboard import DASHBOARD_HTML  # type: ignore[attr-defined]

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not os.environ.get("E2E"),
        reason="E2E tests require E2E=1 environment variable",
    ),
]

# ── Mock API Data ──

MOCK_STATUS: dict[str, Any] = {
    "server": {
        "profile": "default",
        "operating_mode": "proxy",
        "transport": "http",
        "host": "127.0.0.1",
        "port": 9090,
    },
    "kicad": {
        "cli_path": "/usr/bin/kicad-cli",
        "version": "8.0.0",
        "ipc_status": "connected",
    },
    "project": {
        "dir": "/home/user/project",
        "pcb": "project.kicad_pcb",
        "sch": "project.kicad_sch",
    },
    "health": {
        "ok": True,
        "status": "healthy",
        "checks": [
            {"name": "KiCad CLI", "status": "ok", "message": "Found"},
            {"name": "IPC Connection", "status": "ok", "message": "Connected"},
        ],
    },
    "timestamp": "2026-06-07T12:00:00Z",
}

MOCK_METRICS: dict[str, Any] = {
    "total_calls": 142,
    "total_errors": 3,
    "call_counts": {"pcb_get_footprints_ok": 42, "sch_get_symbols_ok": 100},
    "latencies": {"p50_ms": 12.5, "p95_ms": 45.0, "p99_ms": 120.0},
    "tool_counts": 87,
    "uptime_seconds": 3600,
    "uptime_human": "1h 0m 0s",
}

MOCK_HEALTH: dict[str, Any] = {
    "ok": True,
    "status": "healthy",
    "version": __version__,
    "uptime": 3600,
}

MOCK_TOOLS: dict[str, Any] = {
    "tools": [
        {
            "name": "pcb_get_footprints",
            "description": "List board footprints",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer", "description": "Page number"},
                    "page_size": {
                        "type": "integer",
                        "description": "Items per page",
                    },
                },
            },
            "annotations": ["read"],
        },
        {
            "name": "sch_add_component",
            "description": "Add a schematic component",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "library": {"type": "string", "description": "Library name"},
                    "symbol_name": {
                        "type": "string",
                        "description": "Symbol name",
                    },
                },
            },
            "annotations": ["write"],
        },
    ],
    "count": 2,
}

MOCK_CONFIG: dict[str, Any] = {
    "kicad_path": "/usr/bin/kicad-cli",
    "transport": "http",
    "host": "127.0.0.1",
    "port": 9090,
    "profile": "default",
    "log_level": "INFO",
    "operating_mode": "write",
}

MOCK_ARTIFACTS: dict[str, Any] = {
    "artifacts": [
        {
            "session_id": "sess-1",
            "target_path": "/project/test.kicad_sch",
            "sheet_path": "/project/test.kicad_sch",
            "png_path": None,
            "svg_path": "/project/output/schematic-renders/live-preview-test.svg",
            "timestamp": 1783527664.0,
        }
    ]
}

MOCK_CONFIG_EXPORT: dict[str, str] = {
    "config": (
        "{\n"
        '  "mcpServers": {\n'
        '    "kicad-mcp": {\n'
        '      "command": "uv",\n'
        '      "args": ["run", "kicad-mcp", "run"]\n'
        "    }\n"
        "  }\n"
        "}"
    ),
    "format": "json",
}

MOCK_SAVE_RESPONSE: dict[str, str] = {
    "status": "ok",
    "message": "Settings saved. Some changes require a restart.",
}

MOCK_SERVER_RESTART: dict[str, str] = {"message": "Restart initiated..."}


# ── HTTP Server Fixture ──


class _DashboardHandler(BaseHTTPRequestHandler):
    """Serves DASHBOARD_HTML at / and /api/dashboard."""

    def do_GET(self) -> None:
        if self.path in ("/", "/ui", "/ui/", "/api/dashboard"):
            html = DASHBOARD_HTML
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ANN401
        pass  # silence HTTP server logs


@pytest.fixture(scope="session")
def dashboard_url() -> Iterator[str]:
    """Start a local HTTP server serving the SPA dashboard HTML.

    Yields the base URL (e.g. http://127.0.0.1:port).
    """
    server = HTTPServer(("127.0.0.1", 0), _DashboardHandler)
    port: int = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


# ── API Route Mock Fixture ──


@pytest.fixture(autouse=True)
def mock_api(page: Page) -> Iterator[None]:
    """Register route handlers that mock all API endpoints."""

    def _handle(route: Route) -> None:
        url = route.request.url
        method = route.request.method

        if "/api/status" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_STATUS),
            )
        elif "/api/metrics" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_METRICS),
            )
        elif "/api/health" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_HEALTH),
            )
        elif "/api/tools" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_TOOLS),
            )
        elif "/api/artifacts/schematic" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_ARTIFACTS),
            )
        elif "/api/artifacts/file" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="image/svg+xml",
                body="<svg xmlns='http://www.w3.org/2000/svg'></svg>",
            )
        elif "/api/config/export" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_CONFIG_EXPORT),
            )
        elif "/api/config" in url and method == "GET":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_CONFIG),
            )
        elif "/api/config" in url and method == "POST":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_SAVE_RESPONSE),
            )
        elif "/api/server/restart" in url and method == "POST":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(MOCK_SERVER_RESTART),
            )
        elif "/api/server/shutdown" in url and method == "POST":
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"message": "Shutdown initiated..."}),
            )
        elif "/api/logs/stream" in url:
            # SSE — single chunk with 2 log entries then close
            body = (
                "data: "
                + json.dumps(
                    {
                        "level": "INFO",
                        "timestamp": "2026-06-07T12:00:00Z",
                        "event": "Server started",
                    }
                )
                + "\n\n"
                + "data: "
                + json.dumps(
                    {
                        "level": "DEBUG",
                        "timestamp": "2026-06-07T12:00:01Z",
                        "event": "IPC connected",
                    }
                )
                + "\n\n"
            )
            route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                },
                body=body,
            )
        else:
            route.fulfill(
                status=404,
                content_type="application/json",
                body=json.dumps({"error": "Not found"}),
            )

    page.route("**/api/**", _handle)
    yield
    page.unroute("**/api/**")


# ── Tests ──


class TestDashboardSPA:
    """E2E tests for the SPA dashboard frontend."""

    def test_spa_loads(self, page: Page, dashboard_url: str) -> None:
        """The SPA loads and shows the dashboard view by default."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        assert page.text_content("#navVersion") == f"v{__version__}"
        assert page.is_visible("#view-dashboard")
        classes = page.get_attribute("#view-dashboard", "class") or ""
        assert "active" in classes

    def test_navigation_switches_views(self, page: Page, dashboard_url: str) -> None:
        """Navigating between views works via hash changes."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")

        views = ["log-viewer", "tools-catalog", "preview", "settings", "setup-wizard"]
        for view in views:
            page.evaluate(f'window.location.hash = "#{view}"')
            page.wait_for_selector(f"#view-{view}", timeout=3000)
            assert page.is_visible(f"#view-{view}")
            classes = page.get_attribute(f"#view-{view}", "class") or ""
            assert "active" in classes, f"view {view} should be active"

    def test_dashboard_shows_status_cards(self, page: Page, dashboard_url: str) -> None:
        """Dashboard view displays server, KiCad, project, and health info."""
        page.goto(dashboard_url)
        # Wait for refreshStatus to populate fields
        page.wait_for_function(
            '() => document.getElementById("s-profile").textContent !== "-"',
            timeout=5000,
        )

        assert page.text_content("#s-profile") == "default"
        assert page.text_content("#s-mode") == "proxy"
        assert page.text_content("#s-transport") == "http"
        assert page.text_content("#s-host") == "127.0.0.1"
        assert page.text_content("#s-port") == "9090"
        assert page.text_content("#k-cli") == "/usr/bin/kicad-cli"
        assert page.text_content("#k-version") == "8.0.0"
        assert page.text_content("#k-ipc") == "connected"
        assert page.text_content("#p-dir") == "/home/user/project"
        assert page.text_content("#p-pcb") == "project.kicad_pcb"
        assert page.text_content("#p-sch") == "project.kicad_sch"
        assert page.text_content("#health-overall") == "healthy"

    def test_dashboard_shows_uptime(self, page: Page, dashboard_url: str) -> None:
        """Uptime is fetched from metrics and displayed."""
        page.goto(dashboard_url)
        page.wait_for_function(
            '() => document.getElementById("s-uptime").textContent !== "-"',
            timeout=5000,
        )
        assert page.text_content("#s-uptime") == "1h 0m 0s"

    def test_dashboard_shows_health_checks(self, page: Page, dashboard_url: str) -> None:
        """Health checks are rendered inside the health card."""
        page.goto(dashboard_url)
        page.wait_for_function(
            '() => document.getElementById("health-overall").textContent !== "-"',
            timeout=5000,
        )
        health_checks = page.text_content("#health-checks") or ""
        assert "KiCad CLI" in health_checks
        assert "IPC Connection" in health_checks

    def test_nav_status_indicator(self, page: Page, dashboard_url: str) -> None:
        """Sidebar status dot and text reflect server health."""
        page.goto(dashboard_url)
        page.wait_for_function(
            '() => document.getElementById("navStatusText").textContent !== "Checking..."',
            timeout=5000,
        )
        assert page.text_content("#navStatusText") == "healthy"
        sd_class = page.get_attribute("#navStatusDot", "class") or ""
        assert "ok" in sd_class

    def test_log_viewer_receives_lines(self, page: Page, dashboard_url: str) -> None:
        """Log viewer shows SSE log lines after navigation."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#log-viewer"')
        page.wait_for_selector("#view-log-viewer")

        # Wait for log lines from SSE mock
        page.wait_for_function(
            '() => document.querySelectorAll("#log-container .line").length >= 2',
            timeout=5000,
        )
        lines = page.query_selector_all("#log-container .line")
        assert len(lines) >= 2

        # Navigation sidebar item should be active
        nav_class = page.get_attribute('[data-view="log-viewer"]', "class") or ""
        assert "active" in nav_class

    def test_log_viewer_filter_buttons(self, page: Page, dashboard_url: str) -> None:
        """Log viewer filter buttons toggle active state."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#log-viewer"')
        page.wait_for_selector("#view-log-viewer")

        # Click Debug filter
        page.click('button[data-level="debug"]')
        debug_btn = page.query_selector('button[data-level="debug"]')
        assert debug_btn is not None
        assert "active" in (debug_btn.get_attribute("class") or "")

        # Click Info filter
        page.click('button[data-level="info"]')
        info_btn = page.query_selector('button[data-level="info"]')
        assert info_btn is not None
        assert "active" in (info_btn.get_attribute("class") or "")

    def test_log_viewer_clear(self, page: Page, dashboard_url: str) -> None:
        """Clear button empties the log container."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#log-viewer"')
        page.wait_for_selector("#view-log-viewer")
        page.wait_for_timeout(1000)

        page.click("button:has-text('Clear')")
        log_html = page.inner_html("#log-container") or ""
        assert log_html == "" or "Server started" not in log_html

    def test_tools_catalog_loads_tools(self, page: Page, dashboard_url: str) -> None:
        """Tools catalog fetches and renders tool cards."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#tools-catalog"')
        page.wait_for_selector("#view-tools-catalog")

        # Wait for tool cards to render
        page.wait_for_selector("#toolGrid .tool-card", timeout=5000)
        cards = page.query_selector_all("#toolGrid .tool-card")
        assert len(cards) == 2

        # Tool names should be visible
        grid_text = page.text_content("#toolGrid") or ""
        assert "pcb_get_footprints" in grid_text
        assert "sch_add_component" in grid_text

    def test_tools_catalog_search_filters(self, page: Page, dashboard_url: str) -> None:
        """Search input filters tool cards by name/keyword."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#tools-catalog"')
        page.wait_for_selector("#view-tools-catalog")
        page.wait_for_selector("#toolGrid .tool-card", timeout=5000)

        # Search for "footprint"
        page.fill("#toolSearch", "footprint")
        page.wait_for_timeout(500)

        cards_after = page.query_selector_all("#toolGrid .tool-card")
        assert len(cards_after) == 1
        card_text = page.text_content("#toolGrid") or ""
        assert "pcb_get_footprints" in card_text
        assert "sch_add_component" not in card_text

    def test_tools_catalog_clear_search(self, page: Page, dashboard_url: str) -> None:
        """Clearing search restores all tools."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#tools-catalog"')
        page.wait_for_selector("#view-tools-catalog")
        page.wait_for_selector("#toolGrid .tool-card", timeout=5000)

        page.fill("#toolSearch", "footprint")
        page.wait_for_timeout(500)

        page.fill("#toolSearch", "")
        page.wait_for_timeout(500)

        cards = page.query_selector_all("#toolGrid .tool-card")
        assert len(cards) == 2

    def test_tools_catalog_shows_tool_count(self, page: Page, dashboard_url: str) -> None:
        """Tools count is displayed after loading."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#tools-catalog"')
        page.wait_for_selector("#view-tools-catalog")
        page.wait_for_selector("#toolGrid .tool-card", timeout=5000)

        count_text = page.text_content("#tools-count") or ""
        assert "2 tools" in count_text

    def test_settings_form_loads_data(self, page: Page, dashboard_url: str) -> None:
        """Settings form is populated with config data."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#settings"')
        page.wait_for_selector("#view-settings")

        # Wait for config to load
        page.wait_for_function(
            '() => document.getElementById("cfg-kicad_path").value !== ""',
            timeout=5000,
        )

        assert page.input_value("#cfg-kicad_path") == "/usr/bin/kicad-cli"
        assert page.input_value("#cfg-transport") == "http"
        assert page.input_value("#cfg-host") == "127.0.0.1"
        assert page.input_value("#cfg-port") == "9090"
        assert page.input_value("#cfg-profile") == "default"
        assert page.input_value("#cfg-log_level") == "INFO"
        assert page.input_value("#cfg-operating_mode") == "write"

    def test_preview_tab_shows_artifact(self, page: Page, dashboard_url: str) -> None:
        """Preview tab lists schematic render artifacts with a timestamp."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#preview"')
        page.wait_for_selector("#view-preview")

        page.wait_for_function(
            '() => document.getElementById("previewGrid").children.length > 0',
            timeout=5000,
        )
        assert page.is_visible("#previewGrid img")
        assert page.get_attribute("#previewGrid img", "src") == (
            "/api/artifacts/file?path=%2Fproject%2Foutput%2Fschematic-renders%2F"
            "live-preview-test.svg"
        )
        card_text = page.text_content("#previewGrid") or ""
        assert "/project/test.kicad_sch" in card_text

    def test_settings_form_save(self, page: Page, dashboard_url: str) -> None:
        """Settings save triggers POST and shows success message."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#settings"')
        page.wait_for_selector("#view-settings")
        page.wait_for_function(
            '() => document.getElementById("cfg-kicad_path").value !== ""',
            timeout=5000,
        )

        # Change a value
        page.fill("#cfg-host", "0.0.0.0")  # noqa: S104

        # Submit
        page.click('button[type="submit"]')
        page.wait_for_selector("#settings-msg .msg", timeout=5000)
        msg_text = page.text_content("#settings-msg") or ""
        assert "saved" in msg_text.lower()

    def test_export_client_config_claude(self, page: Page, dashboard_url: str) -> None:
        """Export Claude Desktop config shows mcpServers snippet."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#settings"')
        page.wait_for_selector("#view-settings")

        page.click('button:has-text("Claude Desktop")')
        page.wait_for_selector("#export-result", timeout=5000)
        assert page.is_visible("#export-result")
        content = page.text_content("#export-result") or ""
        assert "mcpServers" in content
        assert "kicad-mcp" in content

    def test_export_client_config_cursor(self, page: Page, dashboard_url: str) -> None:
        """Export Cursor config button works."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#settings"')
        page.wait_for_selector("#view-settings")

        page.click('button:has-text("Cursor")')
        page.wait_for_selector("#export-result", timeout=5000)
        assert page.is_visible("#export-result")

    def test_setup_wizard_detection_step(self, page: Page, dashboard_url: str) -> None:
        """Setup wizard step 1 shows KiCad detection from /api/status."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")

        # Step 1: KiCad Detection
        page.wait_for_selector("#wizardBody", timeout=5000)

        # Wait for the fetch to complete and render KiCad info
        page.wait_for_function(
            '() => document.querySelector("#wizardBody .msg") !== null',
            timeout=5000,
        )
        body_text = page.text_content("#wizardBody") or ""
        assert "KiCad CLI found" in body_text
        assert "Version" in body_text
        assert "IPC Status" in body_text

    def test_setup_wizard_transport_step(self, page: Page, dashboard_url: str) -> None:
        """Setup wizard step 2 shows transport selection."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")
        page.wait_for_selector("#wizardBody", timeout=5000)

        # Advance to step 2 (project), then step 3 (transport)
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizProjectDir", timeout=3000)
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizTransport", timeout=3000)
        assert page.is_visible("#wizTransport")
        assert page.is_visible("#wizHost")

    def test_setup_wizard_client_step(self, page: Page, dashboard_url: str) -> None:
        """Setup wizard step 3 shows client selection and preview."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")
        page.wait_for_selector("#wizardBody", timeout=5000)

        # Advance to step 2 (project)
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizProjectDir", timeout=3000)

        # Advance to step 3 (transport)
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizTransport", timeout=3000)

        # Advance to step 4 (client)
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizClient", timeout=3000)
        assert page.is_visible("#wizClient")

        # Click preview config
        page.click('button:has-text("Preview Config")')
        page.wait_for_selector("#wizConfigPreview", timeout=5000)
        assert page.is_visible("#wizConfigPreview")
        preview_text = page.text_content("#wizConfigPreview") or ""
        assert "mcpServers" in preview_text

    def test_setup_wizard_finish_step(self, page: Page, dashboard_url: str) -> None:
        """Setup wizard step 4 allows test connection and finish."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")
        page.wait_for_selector("#wizardBody", timeout=5000)

        # Advance through steps 1-4
        for _ in range(4):
            page.click('button:has-text("Next")')
            page.wait_for_timeout(500)

        # Step 4: Test & Finish
        page.wait_for_selector('button:has-text("Test Connection")', timeout=3000)

        # Test connection
        page.click('button:has-text("Test Connection")')
        page.wait_for_selector("#testResult.success", timeout=5000)
        result_text = page.text_content("#testResult") or ""
        assert "Server" in result_text
        assert "online" in result_text

        # Finish returns to dashboard
        page.click('button:has-text("Finish")')
        page.wait_for_timeout(500)
        assert page.is_visible("#view-dashboard")

    def test_setup_wizard_cancel(self, page: Page, dashboard_url: str) -> None:
        """Cancel button returns to dashboard."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")
        page.wait_for_selector("#wizardBody", timeout=5000)

        page.click('button:has-text("Cancel")')
        page.wait_for_timeout(500)
        assert page.is_visible("#view-dashboard")

    def test_setup_wizard_back_navigation(self, page: Page, dashboard_url: str) -> None:
        """Back button navigates to previous wizard step."""
        page.goto(dashboard_url)
        page.wait_for_selector("#navVersion")
        page.evaluate('window.location.hash = "#setup-wizard"')
        page.wait_for_selector("#view-setup-wizard")
        page.wait_for_selector("#wizardBody", timeout=5000)

        # Step 1 -> 2
        page.click('button:has-text("Next")')
        page.wait_for_selector("#wizProjectDir", timeout=3000)

        # Step 2 -> back to 1
        page.click('button:has-text("Back")')
        page.wait_for_timeout(500)

        # Should show KiCad detection again (no more transport selector)
        assert not page.is_visible("#wizTransport")
