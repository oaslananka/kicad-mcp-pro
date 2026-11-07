"""Session-bound local controls, safe previews, and durable setup progress."""

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.services.cloud_onboarding import OnboardingStep, SetupProgress, SetupStatus
from kicad_mcp.web.routes import web_routes

ORIGIN = "http://127.0.0.1:3334"


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from kicad_mcp.config import reset_config

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
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as client:
        yield client
    reset_config()


def approve(browser: TestClient) -> dict[str, str]:
    response = browser.get("/api/owner/session")
    assert response.status_code == 200
    assert "HttpOnly" in response.headers.get("set-cookie", "")
    assert "SameSite=strict" in response.headers.get("set-cookie", "")
    assert response.headers["cache-control"] == "no-store"
    return {"Origin": ORIGIN, "X-KiCad-Owner-CSRF": response.json()["csrf_token"]}


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "null",
        "https://example.org",
        "http://127.0.0.1:9999",
        "http://localhost:3334",
        "tauri://localhost",
    ],
)
def test_mutations_reject_missing_foreign_and_wrong_port_origins(browser, origin) -> None:
    headers = approve(browser)
    if origin is None:
        headers.pop("Origin")
    else:
        headers["Origin"] = origin
    assert (
        browser.post(
            "/api/cloud/setup/cancel", headers=headers, json={"session_id": "owned"}
        ).status_code
        == 403
    )
    browser.app.state.owner_services.onboarding.cancel_setup.assert_not_called()


def test_mutation_requires_both_cookie_and_csrf(browser) -> None:
    headers = approve(browser)
    assert (
        browser.post("/api/cloud/setup/cancel", headers={"Origin": ORIGIN}, json={}).status_code
        == 403
    )
    browser.cookies.clear()
    assert browser.post("/api/cloud/setup/cancel", headers=headers, json={}).status_code == 403


@pytest.mark.parametrize(
    "host", ["evil.example", "localhost.evil.example", "127.0.0.1@evil.example"]
)
def test_session_denies_rebinding_host(browser, host) -> None:
    assert browser.get("/api/owner/session", headers={"Host": host}).status_code == 403


def test_remote_peer_cannot_create_owner_session() -> None:
    with TestClient(
        Starlette(routes=web_routes), base_url=ORIGIN, client=("198.51.100.2", 50000)
    ) as client:
        assert client.get("/api/owner/session").status_code == 403


def test_setup_progress_is_owned_and_shared_between_requests(browser, tmp_path) -> None:
    headers = approve(browser)
    svc = browser.app.state.owner_services.onboarding
    svc.start_setup.return_value = SimpleNamespace(
        session_id="setup-one",
        current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
        approval_url="https://kicad-mcp-pro.oaslananka.dev/devices/pair",
        user_code="ABCD-1234",
    )
    svc.get_setup_status.return_value = SetupProgress(
        session_id="setup-one",
        status=SetupStatus.PAIRING_PENDING,
        step=OnboardingStep.DEVICE_PAIRING_PENDING,
    )
    response = browser.post(
        "/api/cloud/setup/start", headers=headers, json={"project_path": str(tmp_path)}
    )
    assert response.status_code == 200
    assert response.json()["session_id"] == "setup-one"
    assert "project_dir" not in response.json()
    status = browser.post(
        "/api/cloud/setup/status", headers=headers, json={"session_id": "setup-one"}
    )
    assert status.json()["status"] == "pairing_pending"
    assert (
        browser.post(
            "/api/cloud/setup/cancel", headers=headers, json={"session_id": "setup-one"}
        ).status_code
        == 200
    )
    svc.cancel_setup.assert_called_once_with("setup-one")


def test_other_session_cannot_poll_or_cancel_setup(browser) -> None:
    headers = approve(browser)
    for action in ("status", "cancel"):
        assert (
            browser.post(
                f"/api/cloud/setup/{action}", headers=headers, json={"session_id": "foreign"}
            ).status_code
            == 404
        )
    browser.app.state.owner_services.onboarding.get_setup_status.assert_not_called()


def test_get_status_cannot_mutate_enrollment(browser) -> None:
    assert browser.get("/api/cloud/setup/status").status_code == 405


@pytest.mark.parametrize(
    "body", [[], {"project_path": 12}, {"project_path": ""}, {"origin": "http://evil.example"}]
)
def test_setup_validates_inputs_before_pairing(browser, body) -> None:
    assert (
        browser.post("/api/cloud/setup/start", headers=approve(browser), json=body).status_code
        == 400
    )
    browser.app.state.owner_services.onboarding.start_setup.assert_not_called()


def test_invalid_oversized_and_non_json_body(browser) -> None:
    headers = {**approve(browser), "Content-Type": "application/json"}
    assert browser.post("/api/cloud/setup/start", headers=headers, content="{").status_code == 400
    assert (
        browser.post(
            "/api/cloud/setup/start", headers=headers, content='{"value":"' + "a" * 17000 + '"}'
        ).status_code
        == 413
    )
    assert (
        browser.post(
            "/api/cloud/setup/start",
            headers={**headers, "Content-Type": "text/plain"},
            content="{}",
        ).status_code
        == 415
    )


def test_connector_routes_await_same_manager(browser) -> None:
    headers = approve(browser)
    assert browser.post("/api/cloud/connector/enable", headers=headers, json={}).status_code == 200
    assert browser.post("/api/cloud/connector/disable", headers=headers, json={}).status_code == 200
    browser.app.state.owner_services.connector.start.assert_awaited_once()
    browser.app.state.owner_services.connector.stop.assert_awaited_once()


def test_unknown_project_is_not_reported_as_success(browser) -> None:
    headers = approve(browser)
    browser.app.state.owner_services.connector.switch_active_project.return_value = False
    assert (
        browser.post(
            "/api/cloud/project/active", headers=headers, json={"project_id": "not-registered"}
        ).status_code
        == 409
    )


def test_repair_requires_single_use_preview(browser) -> None:
    from kicad_mcp.services.maintenance import RepairPreview, RepairResult

    headers = approve(browser)
    svc = browser.app.state.owner_services.maintenance
    svc.preview_repair.return_value = RepairPreview(healthy=False, items=[])
    svc.apply_repair.return_value = RepairResult(success=True, repaired_items=[], message="Checked")
    assert (
        browser.post("/api/maintenance/repair/apply", headers=headers, json={}).status_code == 409
    )
    confirmation = browser.get("/api/maintenance/repair/preview").json()["confirmation"]
    assert (
        browser.post(
            "/api/maintenance/repair/apply", headers=headers, json={"confirmation": confirmation}
        ).status_code
        == 200
    )
    assert (
        browser.post(
            "/api/maintenance/repair/apply", headers=headers, json={"confirmation": confirmation}
        ).status_code
        == 409
    )
    svc.apply_repair.assert_called_once()


def test_cleanup_requires_unchanged_preview(browser) -> None:
    from kicad_mcp.services.maintenance import CleanupPreview

    headers = approve(browser)
    svc = browser.app.state.owner_services.maintenance
    svc.preview_cleanup.return_value = CleanupPreview(
        targets_to_remove=["original"], preserved_user_files=[]
    )
    confirmation = browser.get("/api/maintenance/cleanup/preview").json()["confirmation"]
    svc.preview_cleanup.return_value = CleanupPreview(
        targets_to_remove=["changed"], preserved_user_files=[]
    )
    assert (
        browser.post(
            "/api/maintenance/cleanup/apply", headers=headers, json={"confirmation": confirmation}
        ).status_code
        == 409
    )
    svc.apply_cleanup.assert_not_called()


def test_errors_do_not_disclose_exception_details(browser, tmp_path) -> None:
    browser.app.state.owner_services.onboarding.start_setup.side_effect = ValueError(
        "sensitive owner material"
    )
    response = browser.post(
        "/api/cloud/setup/start", headers=approve(browser), json={"project_path": str(tmp_path)}
    )
    assert response.status_code == 400
    assert "sensitive owner material" not in response.text


def test_failed_connector_start_cannot_report_ready(browser: TestClient) -> None:
    headers = approve(browser)
    connector = browser.app.state.owner_services.connector
    connector.start.return_value = False
    connector.is_running = Mock(return_value=False)
    response = browser.post("/api/cloud/connector/enable", headers=headers, json={})
    assert response.status_code == 409
    assert response.json().get("ok") is not True


def test_setup_ids_are_bound_to_the_browser_session(browser: TestClient, tmp_path: Path) -> None:
    headers = approve(browser)
    service = browser.app.state.owner_services.onboarding
    service.start_setup.return_value = SimpleNamespace(
        session_id="private-setup",
        current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
        approval_url=None,
        user_code=None,
    )
    assert (
        browser.post(
            "/api/cloud/setup/start", headers=headers, json={"project_path": str(tmp_path)}
        ).status_code
        == 200
    )

    with TestClient(browser.app, base_url=ORIGIN, client=("127.0.0.1", 50001)) as other:
        second = other.get("/api/owner/session")
        assert second.status_code == 200
        other_headers = {
            "Origin": ORIGIN,
            "X-KiCad-Owner-CSRF": second.json()["csrf_token"],
        }
        for action in ("status", "cancel"):
            result = other.post(
                f"/api/cloud/setup/{action}",
                headers=other_headers,
                json={"session_id": "private-setup"},
            )
            assert result.status_code == 404
    service.cancel_setup.assert_not_called()
    service.get_setup_status.assert_not_called()


@pytest.mark.parametrize("origin", ["null", "https://evil.example", "http://localhost:3334"])
def test_owner_session_refuses_cross_origin_get(browser: TestClient, origin: str) -> None:
    response = browser.get("/api/owner/session", headers={"Origin": origin})
    assert response.status_code == 403
    assert "csrf_token" not in response.text


def test_update_quiesce_rejects_active_cloud_connector(browser: TestClient) -> None:
    from kicad_mcp.web.state import reset_maintenance_for_tests

    reset_maintenance_for_tests()
    headers = approve(browser)
    connector = browser.app.state.owner_services.connector
    connector.get_status.return_value = SimpleNamespace(state="connected")
    try:
        response = browser.post("/api/maintenance/quiesce", headers=headers, json={})
        assert response.status_code == 409
        assert "token" not in response.json()
        connector.get_status.return_value = SimpleNamespace(state="off")
        response = browser.post("/api/maintenance/quiesce", headers=headers, json={})
        assert response.status_code == 200
        token = response.json()["token"]
        assert (
            browser.post(
                "/api/maintenance/resume", headers=headers, json={"token": token}
            ).status_code
            == 200
        )
    finally:
        reset_maintenance_for_tests()


def test_https_owner_session_cookie_has_secure_attribute(browser: TestClient) -> None:
    """When an HTTPS loopback origin is used, cookies are transport-secure."""
    with TestClient(
        browser.app,
        base_url="https://127.0.0.1:3334",
        client=("127.0.0.1", 50002),
    ) as https_client:
        response = https_client.get("/api/owner/session")
    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]
