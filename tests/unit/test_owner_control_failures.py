"""Negative HTTP owner-control paths that must not mutate application state."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.config import reset_config
from kicad_mcp.services.maintenance import CleanupResult, RepairPreview
from kicad_mcp.web.routes import web_routes

ORIGIN = "http://127.0.0.1:3334"


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    reset_config()
    app = Starlette(routes=web_routes)
    app.state.owner_services = SimpleNamespace(
        onboarding=Mock(),
        maintenance=Mock(),
        connector=SimpleNamespace(
            start=AsyncMock(return_value=True),
            stop=AsyncMock(return_value=True),
            switch_active_project=AsyncMock(return_value=True),
            get_status=Mock(return_value=SimpleNamespace(state="off")),
        ),
    )
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 54000)) as client:
        yield client
    reset_config()


def approved(browser: TestClient) -> dict[str, str]:
    response = browser.get("/api/owner/session")
    assert response.status_code == 200
    return {"Origin": ORIGIN, "X-KiCad-Owner-CSRF": response.json()["csrf_token"]}


def test_start_failure_reports_generic_error_without_path_or_credentials(
    browser: TestClient,
) -> None:
    svc = browser.app.state.owner_services.onboarding
    svc.start_setup.side_effect = OSError("private-key-file: forbidden")
    response = browser.post(
        "/api/cloud/setup/start",
        headers=approved(browser),
        json={"project_path": "C:/Project"},
    )
    assert response.status_code == 400
    assert "private-key-file" not in response.text


def test_cancel_failed_session_does_not_report_success(browser: TestClient) -> None:
    headers = approved(browser)
    svc = browser.app.state.owner_services.onboarding
    svc.start_setup.return_value = SimpleNamespace(
        session_id="mine",
        current_step=SimpleNamespace(value="device_pairing_pending"),
        approval_url=None,
        user_code=None,
    )
    assert (
        browser.post(
            "/api/cloud/setup/start", headers=headers, json={"project_path": "C:/board"}
        ).status_code
        == 200
    )
    svc.cancel_setup.return_value = False
    cancelled = browser.post(
        "/api/cloud/setup/cancel", headers=headers, json={"session_id": "mine"}
    )
    assert cancelled.status_code == 404


@pytest.mark.parametrize("method", ["enable", "disable"])
def test_connector_failures_are_explicit(browser: TestClient, method: str) -> None:
    headers = approved(browser)
    connector = browser.app.state.owner_services.connector
    getattr(connector, "start" if method == "enable" else "stop").side_effect = RuntimeError("bad")
    response = browser.post(f"/api/cloud/connector/{method}", headers=headers, json={})
    assert response.status_code == 409
    assert response.json().get("ok") is not True


def test_connector_already_running_reports_accurate_state(browser: TestClient) -> None:
    headers = approved(browser)
    connector = browser.app.state.owner_services.connector
    connector.start.return_value = False
    connector.is_running = Mock(return_value=True)
    response = browser.post("/api/cloud/connector/enable", headers=headers, json={})
    assert response.status_code == 200
    assert response.json()["status"] == "already_running"


def test_switching_project_failure_is_not_a_success(browser: TestClient) -> None:
    headers = approved(browser)
    browser.app.state.owner_services.connector.switch_active_project.side_effect = OSError(
        "registry unavailable"
    )
    response = browser.post(
        "/api/cloud/project/active", headers=headers, json={"project_id": "another"}
    )
    assert response.status_code == 409
    assert response.json().get("ok") is not True


@pytest.mark.parametrize("kind", ["repair", "cleanup"])
def test_broken_maintenance_preview_fails_closed(browser: TestClient, kind: str) -> None:
    approved(browser)
    svc = browser.app.state.owner_services.maintenance
    getattr(svc, f"preview_{kind}").side_effect = OSError("secret filename")
    response = browser.get(f"/api/maintenance/{kind}/preview")
    assert response.status_code == 409
    assert "secret filename" not in response.text


def test_maintenance_apply_error_consumes_confirmation(browser: TestClient) -> None:
    headers = approved(browser)
    svc = browser.app.state.owner_services.maintenance
    svc.preview_repair.return_value = RepairPreview(healthy=False, items=[])
    svc.apply_repair.side_effect = OSError("file locked")
    preview = browser.get("/api/maintenance/repair/preview")
    assert preview.status_code == 200
    confirmation = preview.json()["confirmation"]
    first = browser.post(
        "/api/maintenance/repair/apply",
        headers=headers,
        json={"confirmation": confirmation},
    )
    assert first.status_code == 409
    assert "file locked" not in first.text
    second = browser.post(
        "/api/maintenance/repair/apply",
        headers=headers,
        json={"confirmation": confirmation},
    )
    assert second.status_code == 409
    svc.apply_repair.assert_called_once()


def test_maintenance_cleanup_false_result_is_not_reported_success(
    browser: TestClient,
) -> None:
    from kicad_mcp.services.maintenance import CleanupPreview

    headers = approved(browser)
    svc = browser.app.state.owner_services.maintenance
    svc.preview_cleanup.return_value = CleanupPreview()
    svc.apply_cleanup.return_value = CleanupResult(success=False, message="retry needed")
    confirmation = browser.get("/api/maintenance/cleanup/preview").json()["confirmation"]
    response = browser.post(
        "/api/maintenance/cleanup/apply",
        headers=headers,
        json={"confirmation": confirmation},
    )
    assert response.status_code == 409
    assert response.json()["ok"] is False


def test_quiesce_state_probe_failure_does_not_grant_update_token(
    browser: TestClient,
) -> None:
    headers = approved(browser)
    connector = browser.app.state.owner_services.connector
    connector.get_status.side_effect = RuntimeError("unavailable")
    response = browser.post("/api/maintenance/quiesce", headers=headers, json={})
    assert response.status_code == 409
    assert "token" not in response.text


def test_resume_denies_missing_and_invalid_lease_token(browser: TestClient) -> None:
    headers = approved(browser)
    for body, expected in [({}, 400), ({"token": "x" * 200}, 400), ({"token": "unknown"}, 409)]:
        response = browser.post("/api/maintenance/resume", headers=headers, json=body)
        assert response.status_code == expected
