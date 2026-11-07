"""Desktop maintenance fencing and authenticated release of the in-process MCP gate."""

from collections.abc import Iterator

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from kicad_mcp.config import reset_config
from kicad_mcp.web.routes import web_routes
from kicad_mcp.web.state import (
    finish_tool_execution,
    reserve_tool_execution,
    reset_maintenance_for_tests,
)

ORIGIN = "http://127.0.0.1:3334"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("KICAD_MCP_HOST", "127.0.0.1")
    reset_config()
    reset_maintenance_for_tests()
    app = Starlette(routes=web_routes)
    with TestClient(app, base_url=ORIGIN, client=("127.0.0.1", 50000)) as browser:
        yield browser
    reset_maintenance_for_tests()
    reset_config()


def _owner_headers(browser: TestClient) -> dict[str, str]:
    session = browser.get("/api/owner/session")
    assert session.status_code == 200
    return {
        "Origin": ORIGIN,
        "X-KiCad-Owner-CSRF": session.json()["csrf_token"],
    }


def test_quiesce_blocks_busy_backend_then_rejects_new_tools(client: TestClient) -> None:
    headers = _owner_headers(client)
    assert reserve_tool_execution()
    busy = client.post("/api/maintenance/quiesce", headers=headers, json={})
    assert busy.status_code == 409
    finish_tool_execution()
    quiesced = client.post("/api/maintenance/quiesce", headers=headers, json={})
    assert quiesced.status_code == 200
    assert quiesced.json()["state"] == "quiesced"
    assert not reserve_tool_execution()
    assert client.post("/api/maintenance/quiesce", headers=headers, json={}).status_code == 409
    resumed = client.post(
        "/api/maintenance/resume",
        headers=headers,
        json={"token": quiesced.json()["token"]},
    )
    assert resumed.status_code == 200
    assert reserve_tool_execution()
    finish_tool_execution()


def test_resume_requires_correct_owner_token_and_is_one_shot(client: TestClient) -> None:
    headers = _owner_headers(client)
    quiesced = client.post("/api/maintenance/quiesce", headers=headers, json={})
    assert quiesced.status_code == 200
    token = quiesced.json()["token"]
    incorrect_token = f"invalid-{token}"
    assert (
        client.post(
            "/api/maintenance/resume", headers=headers, json={"token": incorrect_token}
        ).status_code
        == 409
    )
    assert not reserve_tool_execution()

    with TestClient(client.app, base_url=ORIGIN, client=("127.0.0.1", 50001)) as other:
        foreign = _owner_headers(other)
        assert (
            other.post(
                "/api/maintenance/resume", headers=foreign, json={"token": token}
            ).status_code
            == 409
        )
    assert (
        client.post("/api/maintenance/resume", headers=headers, json={"token": token}).status_code
        == 200
    )
    assert (
        client.post("/api/maintenance/resume", headers=headers, json={"token": token}).status_code
        == 409
    )


def test_quiesce_rejects_cross_origin_and_missing_csrf(client: TestClient) -> None:
    headers = _owner_headers(client)
    assert (
        client.post(
            "/api/maintenance/quiesce",
            headers={
                "Origin": "https://attacker.example",
                **{"X-KiCad-Owner-CSRF": headers["X-KiCad-Owner-CSRF"]},
            },
            json={},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/maintenance/quiesce", headers={"Origin": ORIGIN}, json={}).status_code
        == 403
    )
    assert reserve_tool_execution()
    finish_tool_execution()
