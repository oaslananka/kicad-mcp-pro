"""Tests for owner-authorized loopback routes in Starlette."""

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.web.routes import web_routes


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=web_routes)
    return TestClient(app, base_url="http://127.0.0.1:3334")


def test_api_experience_returns_valid_snapshot(client) -> None:
    response = client.get("/api/experience")
    assert response.status_code == 200
    data = response.json()
    assert "readiness" in data
    assert "engine_capabilities" in data
    assert "next_action" in data


def test_mutating_routes_reject_foreign_origin(client) -> None:
    headers = {"Origin": "https://malicious-website.com"}
    response = client.post("/api/cloud/setup/cancel", headers=headers)
    assert response.status_code == 403
    assert "Origin not allowed" in response.text


def test_mutating_routes_accept_loopback_origin(client) -> None:
    headers = {"Origin": "http://127.0.0.1:3334"}
    response = client.post("/api/cloud/setup/cancel", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data.get("ok") is True


def test_maintenance_routes(client) -> None:
    res_preview = client.get("/api/maintenance/repair/preview")
    assert res_preview.status_code == 200
    assert "healthy" in res_preview.json()

    res_clean_preview = client.get("/api/maintenance/cleanup/preview")
    assert res_clean_preview.status_code == 200
    assert "preserved_user_files" in res_clean_preview.json()
