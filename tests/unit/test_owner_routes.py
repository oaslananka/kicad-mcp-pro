"""Tests for owner-authorized loopback routes in Starlette."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.web import routes as route_module
from kicad_mcp.web.routes import web_routes


@pytest.fixture
def client() -> TestClient:
    app = Starlette(routes=web_routes)
    return TestClient(app, base_url="http://127.0.0.1:3334", client=("127.0.0.1", 50000))


def test_api_experience_returns_valid_snapshot(client) -> None:
    assert client.get("/api/owner/session").status_code == 200
    response = client.get("/api/experience")
    assert response.status_code == 200
    data = response.json()
    assert "readiness" in data
    assert "engine_capabilities" in data
    assert "next_action" in data


def test_mutating_routes_reject_foreign_origin(client) -> None:
    session = client.get("/api/owner/session")
    assert session.status_code == 200
    headers = {
        "Origin": "https://malicious-website.com",
        "X-KiCad-Owner-CSRF": session.json()["csrf_token"],
    }
    response = client.post("/api/cloud/setup/cancel", headers=headers)
    assert response.status_code == 403
    assert "Origin not allowed" in response.text


def test_mutating_routes_accept_loopback_origin(client) -> None:
    session = client.get("/api/owner/session")
    assert session.status_code == 200
    headers = {
        "Origin": "http://127.0.0.1:3334",
        "X-KiCad-Owner-CSRF": session.json()["csrf_token"],
    }
    response = client.post(
        "/api/cloud/setup/cancel", headers=headers, json={"session_id": "unknown"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "Setup not found"


def test_maintenance_routes(client) -> None:
    assert client.get("/api/owner/session").status_code == 200
    res_preview = client.get("/api/maintenance/repair/preview")
    assert res_preview.status_code == 200
    assert "healthy" in res_preview.json()

    res_clean_preview = client.get("/api/maintenance/cleanup/preview")
    assert res_clean_preview.status_code == 200
    assert "preserved_user_files" in res_clean_preview.json()


def test_experience_denies_anonymous_local_project_access(client: TestClient) -> None:
    response = client.get("/api/experience")
    assert response.status_code == 403
    assert "project" not in response.text


def test_local_experience_uses_real_project_and_saved_file_capability(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ("g" + chr(252) + chr(231) + "-kart" + chr(305) + ".kicad_pro")).write_text(
        "{}", encoding="utf-8"
    )
    monkeypatch.setattr(
        route_module,
        "get_config",
        lambda: SimpleNamespace(project_dir=tmp_path, kicad_cli=tmp_path / "missing-cli"),
    )
    monkeypatch.setattr(route_module, "find_kicad_version", lambda *_: None)
    monkeypatch.setattr(
        route_module,
        "get_ipc_capability_state",
        lambda: SimpleNamespace(live_pcb_read=False, live_schematic_read=False),
    )
    assert client.get("/api/experience").status_code == 403
    assert client.get("/api/owner/session").status_code == 200
    response = client.get("/api/experience")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["readiness"] == "ready"
    assert result["project"]["path"] == str(tmp_path)
    assert result["engine_capabilities"]["file_available"] is True
    assert result["engine_capabilities"]["ipc_available"] is False
    assert "run_drc" not in result["available_actions"]
    assert "open_project" in result["available_actions"]


def test_local_drc_is_only_offered_when_cli_detected(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        route_module,
        "get_config",
        lambda: SimpleNamespace(project_dir=tmp_path, kicad_cli=tmp_path / "kicad-cli"),
    )
    monkeypatch.setattr(route_module, "find_kicad_version", lambda *_: "10.0.8")
    monkeypatch.setattr(
        route_module,
        "get_ipc_capability_state",
        lambda: SimpleNamespace(live_pcb_read=False, live_schematic_read=False),
    )
    assert client.get("/api/owner/session").status_code == 200
    response = client.get("/api/experience")
    assert response.status_code == 200
    assert "run_drc" in response.json()["available_actions"]
