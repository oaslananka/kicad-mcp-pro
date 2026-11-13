"""CLI management is owner-approved, token-scoped and no-redirect; no live Cloud calls."""

from __future__ import annotations

import os

import pytest
from typer.testing import CliRunner

from kicad_mcp import cloud_owner_cli, cloud_owner_management
from kicad_mcp.cloud_owner_management import CloudManagementError, CloudOwnerApi
from kicad_mcp.server import app

_ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"
_TOKEN = "kmpc1_" + "a" * 43


def test_owner_api_uses_verified_tls_and_never_forwards_token_on_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []

    class FakeReply:
        status = 200

        def read(self, _size: int) -> bytes:
            return b'{"devices":[]}'

        def release_conn(self) -> None:
            calls.append(("release",))

    class FakePool:
        def request(self, method: str, url: str, **kwargs: object) -> FakeReply:
            calls.append((method, url, kwargs))
            return FakeReply()

        def clear(self) -> None:
            calls.append(("clear",))

    monkeypatch.setattr(cloud_owner_management.urllib3, "PoolManager", lambda **_: FakePool())
    answer = CloudOwnerApi(_ORIGIN).request("GET", "/api/owner/v1/devices", token=_TOKEN)
    assert answer == {"devices": []}
    method, url, params = calls[0]
    assert method == "GET"
    assert url == _ORIGIN + "/api/owner/v1/devices"
    assert params["redirect"] is False
    assert params["headers"]["Authorization"] == "Bearer " + _TOKEN
    assert calls[-2:] == [("release",), ("clear",)]


def test_owner_api_refuses_http_redirect_and_oversized_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeReply:
        status = 302

        def read(self, _size: int) -> bytes:
            raise AssertionError("Redirect responses must not be parsed")

        def release_conn(self) -> None:
            pass

    class FakePool:
        def request(self, *_args: object, **kw: object) -> FakeReply:
            assert kw["redirect"] is False
            return FakeReply()

        def clear(self) -> None:
            pass

    monkeypatch.setattr(cloud_owner_management.urllib3, "PoolManager", lambda **_: FakePool())
    with pytest.raises(CloudManagementError, match="HTTP 302"):
        CloudOwnerApi(_ORIGIN).request("GET", "/api/owner/v1/devices", token=_TOKEN)
    with pytest.raises(CloudManagementError, match="HTTPS"):
        CloudOwnerApi("http://untrusted.invalid")


def test_approve_browser_once_then_store_only_valid_management_token(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: list[tuple[object, ...]] = []
    request_id = "Z" * 43
    states = iter(("pending", "approved"))
    monkeypatch.setattr(cloud_owner_management.secrets, "token_urlsafe", lambda _: request_id)
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _: None)
    monkeypatch.setattr(
        cloud_owner_management,
        "save_token",
        lambda origin, token: seen.append(("saved", origin, token)),
    )
    monkeypatch.setattr(
        cloud_owner_management.webbrowser,
        "open",
        lambda url, **_: seen.append(("browser", url)) or True,
    )
    monkeypatch.setattr(cloud_owner_management.time, "sleep", lambda _: None)

    def fake_request(
        self: CloudOwnerApi,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        token: str | None = None,
    ) -> dict[str, object]:
        assert token is None
        assert method == "POST"
        if path.endswith("/start"):
            assert payload == {"requestId": request_id, "label": "Office PC"}
            return {
                "status": "pending",
                "approveUrl": (_ORIGIN + "/api/owner/cli/approve?request_id=" + request_id),
            }
        assert path.endswith("/poll")
        state = next(states)
        return {"status": state, **({"token": _TOKEN} if state == "approved" else {})}

    monkeypatch.setattr(CloudOwnerApi, "request", fake_request)
    cloud_owner_management.authorize(_ORIGIN, label="Office PC", timeout_seconds=30)
    assert seen[0] == ("browser", _ORIGIN + "/api/owner/cli/approve?request_id=" + request_id)
    assert seen[1] == ("saved", _ORIGIN, _TOKEN)
    assert _TOKEN not in capsys.readouterr().out


def test_cli_devices_projects_access_and_write_routes_are_real(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    routes: list[tuple[str, str, object]] = []

    def fake_request(
        origin: str,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        routes.append((method, path, body))
        assert origin == _ORIGIN
        if path.endswith("/devices"):
            return {
                "devices": [
                    {
                        "id": "device-id",
                        "alias": "My workstation",
                        "connected": True,
                        "projects": [{"id": "project-id", "alias": "Motor Board", "enabled": True}],
                    }
                ]
            }
        if path.endswith("/clients"):
            return {"clients": [{"clientId": "approved-ai", "consentedAt": "2026-11-13"}]}
        if path.endswith("/access"):
            return {"access": []}
        if path.endswith("/logs?limit=5"):
            return {"events": []}
        if path.endswith("/usage?days=7"):
            return {"summary": {"count": 14}}
        return {"updated": True, "maxMode": "readonly"}

    monkeypatch.setattr(cloud_owner_cli, "_request", fake_request)
    runner = CliRunner()
    cases = [
        (["cloud", "devices", "--json"], "My workstation"),
        (["cloud", "projects", "--cloud", "--json"], "Motor Board"),
        (["cloud", "clients", "--json"], "approved-ai"),
        (["cloud", "access", "--json"], '"access"'),
        (["cloud", "usage", "--days", "7", "--json"], "14"),
        (["cloud", "logs", "--limit", "5", "--json"], '"events"'),
        (
            [
                "cloud",
                "set-access",
                "--project-id",
                "project-id",
                "--client-id",
                "approved-ai",
                "--enabled",
            ],
            "readonly",
        ),
        (
            [
                "cloud",
                "set-access",
                "--project-id",
                "project-id",
                "--client-id",
                "approved-ai",
                "--disabled",
            ],
            "readonly",
        ),
    ]
    for args, expected in cases:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert expected in result.output
    assert (
        "POST",
        "/api/owner/v1/access/set",
        {
            "projectId": "project-id",
            "clientId": "approved-ai",
            "enabled": True,
        },
    ) in routes
    assert (
        "POST",
        "/api/owner/v1/access/set",
        {
            "projectId": "project-id",
            "clientId": "approved-ai",
            "enabled": False,
        },
    ) in routes


def test_owner_api_without_approval_fails_without_exposing_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _: None)
    result = CliRunner().invoke(app, ["cloud", "devices", "--json"])
    assert result.exit_code != 0
    assert "cloud authorize" in result.output


@pytest.mark.skipif(os.name != "posix", reason="POSIX private file semantics")
def test_posix_token_is_private_and_removable(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pathlib import Path

    root = Path(str(tmp_path)) / "owned"
    monkeypatch.setattr(cloud_owner_management, "default_registry_root", lambda: root)
    cloud_owner_management.save_token(_ORIGIN, _TOKEN)
    _, filename = cloud_owner_management._posix_file(_ORIGIN)
    saved = root / filename
    assert saved.stat().st_mode & 0o077 == 0
    assert cloud_owner_management.load_token(_ORIGIN) == _TOKEN
    cloud_owner_management.forget_token(_ORIGIN)
    assert not saved.exists()
