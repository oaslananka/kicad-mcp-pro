"""User-first local project / AI / optional Cloud flow contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp import cloud_user_cli
from kicad_mcp.config import reset_config
from kicad_mcp.web import owner_routes
from kicad_mcp.web.dashboard import DASHBOARD_HTML
from kicad_mcp.web.routes import web_routes

ORIGIN = "http://127.0.0.1:3334"


@pytest.fixture
def owner_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    monkeypatch.setenv("KICAD_MCP_PORT", "3334")
    reset_config()
    with TestClient(
        Starlette(routes=web_routes), base_url=ORIGIN, client=("127.0.0.1", 50000)
    ) as browser:
        yield browser
    reset_config()


def owner_headers(browser: TestClient) -> dict[str, str]:
    result = browser.get("/api/owner/session")
    assert result.status_code == 200
    return {"Origin": ORIGIN, "X-KiCad-Owner-CSRF": result.json()["csrf_token"]}


def test_project_picker_never_works_without_same_origin_csrf(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    browser = owner_client
    calls: list[str] = []

    def choose() -> Path:
        calls.append("picker")
        return tmp_path

    monkeypatch.setattr(cloud_user_cli, "_browse_local_project_folder", choose)
    assert browser.post("/api/owner/project/browse", json={}).status_code == 403
    token = owner_headers(browser)
    assert (
        browser.post("/api/owner/project/browse", json={}, headers={"Origin": ORIGIN}).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/owner/project/browse",
            json={},
            headers={**token, "Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert calls == []
    assert (
        browser.post("/api/owner/project/select", json={"project_dir": str(tmp_path)}).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/owner/project/select",
            json={"project_dir": str(tmp_path)},
            headers={"Origin": ORIGIN},
        ).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/owner/project/select",
            json={"project_dir": str(tmp_path), "host": "other"},
            headers=token,
        ).status_code
        == 400
    )

    selected = browser.post("/api/owner/project/browse", json={}, headers=token)
    assert selected.status_code == 200
    assert selected.json() == {"project_dir": str(tmp_path.resolve())}
    assert calls == ["picker"]


def test_native_picker_cancellation_is_recoverable(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    browser = owner_client

    def cancel() -> Path:
        raise ValueError("cancelled")

    monkeypatch.setattr(cloud_user_cli, "_browse_local_project_folder", cancel)
    response = browser.post("/api/owner/project/browse", json={}, headers=owner_headers(browser))
    assert response.status_code == 409
    assert "Enter a local project folder" in response.json()["error"]
    assert "cancelled" not in response.text


def test_dashboard_exposes_one_first_use_path_and_optional_cloud() -> None:
    html = DASHBOARD_HTML
    assert 'class="gp-steps"' in html
    assert html.count('class="gp-card') == 3
    assert 'id="gpBrowse"' in html
    assert 'id="gpSaveProject"' in html
    assert 'id="gpAiPreview"' in html
    assert 'id="gpAiApply"' in html
    assert 'id="gpCloudPair"' in html
    assert 'id="gpCheckPair"' in html
    assert 'id="gpCancelPair"' in html
    assert 'id="gpEnableConnector"' in html
    assert "gpLoadProject();" in html
    assert "Cloud is optional." in html
    assert "Cloud access has not been verified" in html


def test_ai_configuration_requires_preview_then_explicit_apply() -> None:
    html = DASHBOARD_HTML
    assert "/api/owner/client-config/preview/" in html
    assert "/api/owner/client-config/apply/" in html
    assert "gpClientPreview = {client, confirmation: data.confirmation}" in html
    assert "gpAiPending" not in html
    assert "Open your AI app and verify its actual MCP connection" in html


def test_windows_connector_enable_and_disable_use_owner_scheduler(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp import cloud_windows_connector, cloud_windows_task_scheduler
    from kicad_mcp.services.connector_lifecycle import ConnectorLifecycleManager

    # Exercise Windows behavior on Linux CI without mutating global os.name.
    monkeypatch.setattr(owner_routes, "os", SimpleNamespace(name="nt"))
    calls: list[str] = []
    registered = object()

    def start(project: object, *, owner_confirm) -> None:
        assert project is registered
        assert owner_confirm(project)
        calls.append("enable")

    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: registered)
    monkeypatch.setattr(cloud_windows_task_scheduler, "enable_windows_connector", start)
    monkeypatch.setattr(
        cloud_windows_task_scheduler,
        "scheduler_state",
        lambda: "Scheduled (connection unverified)",
    )
    monkeypatch.setattr(
        cloud_windows_task_scheduler,
        "disable_windows_connector",
        lambda: calls.append("disable") or True,
    )
    owner_client.app.state.owner_services = SimpleNamespace(
        connector=ConnectorLifecycleManager(registry_root=tmp_path / "registry"),
        onboarding=object(),
        maintenance=object(),
    )
    headers = owner_headers(owner_client)
    enabled = owner_client.post("/api/cloud/connector/enable", headers=headers, json={})
    assert enabled.status_code == 200
    assert enabled.json() == {"ok": True, "status": "Scheduled (connection unverified)"}
    assert calls == ["enable"]

    disabled = owner_client.post("/api/cloud/connector/disable", headers=headers, json={})
    assert disabled.status_code == 200
    assert disabled.json() == {"ok": True, "status": "disabled"}
    assert calls == ["enable", "disable"]

    monkeypatch.setattr(cloud_windows_task_scheduler, "disable_windows_connector", lambda: False)
    unverified = owner_client.post("/api/cloud/connector/disable", headers=headers, json={})
    assert unverified.status_code == 409
    assert "unverified" in unverified.json()["error"]

    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: None)
    no_project = owner_client.post("/api/cloud/connector/enable", headers=headers, json={})
    assert no_project.status_code == 409
    assert "No owner-selected" in no_project.json()["error"]

    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: registered)

    def broken_enable(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("private path never shown")

    monkeypatch.setattr(cloud_windows_task_scheduler, "enable_windows_connector", broken_enable)
    failed_enable = owner_client.post("/api/cloud/connector/enable", headers=headers, json={})
    assert failed_enable.status_code == 409
    assert failed_enable.json()["error"] == "Windows Connector could not be scheduled"

    def broken_disable():
        raise OSError("secret from Windows scheduler")

    monkeypatch.setattr(cloud_windows_task_scheduler, "disable_windows_connector", broken_disable)
    failed_disable = owner_client.post("/api/cloud/connector/disable", headers=headers, json={})
    assert failed_disable.status_code == 409
    assert failed_disable.json()["error"] == "Windows Connector shutdown could not be verified"


def test_windows_browser_approval_cannot_claim_cancelled(
    owner_client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from kicad_mcp.services.cloud_onboarding import OnboardingStep
    from kicad_mcp.services.cloud_windows_onboarding_ui import WindowsCloudOnboardingService

    monkeypatch.setattr(owner_routes, "os", SimpleNamespace(name="nt"))
    enrollment = WindowsCloudOnboardingService()
    monkeypatch.setattr(
        enrollment,
        "start_setup",
        lambda **_kwargs: SimpleNamespace(
            session_id="native-test",
            current_step=OnboardingStep.DEVICE_PAIRING_PENDING,
            approval_url=None,
            user_code=None,
        ),
    )
    monkeypatch.setattr(enrollment, "cancel_setup", lambda _sid: False)
    owner_client.app.state.owner_services = SimpleNamespace(
        onboarding=enrollment, connector=object(), maintenance=object()
    )
    headers = owner_headers(owner_client)
    started = owner_client.post(
        "/api/cloud/setup/start",
        headers=headers,
        json={"project_path": str(tmp_path)},
    )
    assert started.status_code == 200
    cancelled = owner_client.post(
        "/api/cloud/setup/cancel", headers=headers, json={"session_id": "native-test"}
    )
    assert cancelled.status_code == 409
    assert "Deny it in the browser" in cancelled.json()["error"]


def test_cloud_registration_never_claims_a_grant_or_autostarts_connector() -> None:
    html = DASHBOARD_HTML
    assert "/api/cloud/setup/start" in html
    assert "/api/cloud/setup/status" in html
    assert "/api/cloud/setup/cancel" in html
    assert "if (++gpPollCount < 90)" in html
    assert "gpTrustedCloudPairLink(data.approval_url)" in html
    assert "gpEnableConnector').addEventListener('click', gpEnableConnector)" in html
    assert "Cloud access is NOT verified" in html
    assert "project and AI-client grants" in html
    assert "gpPostOwner('/api/cloud/connector/enable')" in html
