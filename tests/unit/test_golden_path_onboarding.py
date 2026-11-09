"""User-first local project / AI / optional Cloud flow contract."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp import cloud_user_cli
from kicad_mcp.config import reset_config
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
