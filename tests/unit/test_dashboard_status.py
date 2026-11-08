"""Tests for dashboard status semantics and connection test logic."""

import re

from kicad_mcp.web.dashboard import DASHBOARD_HTML


def test_dashboard_connection_test_does_not_treat_ok_false_as_success() -> None:
    """Verify testConnection in DASHBOARD_HTML distinguishes ok:false from success."""
    # The script must check d.ok before assigning success
    # Previous bug: el.className = 'wizard-result success' unconditional on JSON parse
    match = re.search(r"function testConnection\(\)\s*\{([\s\S]*?)\n\}", DASHBOARD_HTML)
    assert match is not None, "testConnection function not found in DASHBOARD_HTML"
    body = match.group(1)

    # Must check response.ok or response status
    assert "r.ok" in body or "response.ok" in body, "testConnection must verify HTTP response.ok"

    # Must check parsed ok flag and not unconditionally set success
    assert "d.ok" in body or "data.ok" in body, "testConnection must verify d.ok"
    assert "wizard-result warn" in body or "wizard-result error" in body, (
        "testConnection must have distinct non-success presentation for ok:false"
    )

    # Must verify malformed JSON or invalid schema is not treated as success
    assert "typeof" in body or "catch" in body, (
        "testConnection must handle invalid or unexpected response"
    )


def test_dashboard_status_distinguishes_degraded_from_error() -> None:
    """Verify refreshStatus or status rendering handles degraded distinctly from error."""
    assert (
        "status-dot.degraded" in DASHBOARD_HTML
        or "status-dot warn" in DASHBOARD_HTML
        or "degraded" in DASHBOARD_HTML
    )


def test_local_cleanup_requires_explicit_preview_and_user_click() -> None:
    from kicad_mcp.web.dashboard import DASHBOARD_HTML

    assert "function previewCleanup()" in DASHBOARD_HTML
    assert "function applyCleanup(confirmation, button)" in DASHBOARD_HTML
    assert "/api/maintenance/cleanup/preview" in DASHBOARD_HTML
    assert "/api/maintenance/cleanup/apply" in DASHBOARD_HTML
    assert "Clean reviewed local settings" in DASHBOARD_HTML
    assert "does not revoke Cloud device or AI access" in DASHBOARD_HTML
