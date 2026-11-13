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


def test_owner_cli_human_readable_layout_keeps_child_projects_and_empty_states(
    capsys: pytest.CaptureFixture[str],
) -> None:
    cloud_owner_cli._display(
        {
            "devices": [
                {
                    "id": "dev",
                    "alias": "Workstation",
                    "projects": [{"id": "board-1", "alias": "Motor Board"}],
                }
            ],
            "clients": [],
            "summary": {"totalCalls": 14, "errors": 2},
            "status": "connected",
            "events": ["one-event"],
        },
        False,
    )
    output = capsys.readouterr().out
    for value in (
        "Workstation",
        "Motor Board",
        "No clients found.",
        "totalCalls: 14",
        "errors: 2",
        "status: connected",
        "one-event",
    ):
        assert value in output


def test_owner_cli_mutating_commands_use_only_approved_owner_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[tuple[str, str, object]] = []

    def fake_request(
        origin: str,
        method: str,
        path: str,
        *,
        body: dict[str, object] | None = None,
    ) -> dict[str, object]:
        assert origin == _ORIGIN
        seen.append((method, path, body))
        return {"updated": True, "removed": True, "revokedProjects": 1}

    monkeypatch.setattr(cloud_owner_cli, "_request", fake_request)
    cases = [
        (
            ["cloud", "rename-project", "--project-id", "pcb-id", "--name", "New Name"],
            ("POST", "/api/owner/v1/projects/rename", {"projectId": "pcb-id", "alias": "New Name"}),
            "updated: True",
        ),
        (
            ["cloud", "remove-project", "--project-id", "pcb-id"],
            ("POST", "/api/owner/v1/projects/remove", {"projectId": "pcb-id"}),
            "Local KiCad files were not changed.",
        ),
        (
            ["cloud", "revoke-client", "--client-id", "chatgpt-client"],
            ("POST", "/api/owner/v1/access/revoke", {"clientId": "chatgpt-client"}),
            "revokedProjects: 1",
        ),
    ]
    for args, expected, text in cases:
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
        assert expected in seen
        assert text in result.output


def test_owner_cli_authorize_and_logout_are_explicit_and_preserve_projects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approved: list[tuple[str, bool, str | None]] = []
    forgotten: list[str] = []
    posted: list[tuple[str, str, str]] = []

    def fake_authorize(origin: str, *, no_browser: bool, label: str | None) -> None:
        approved.append((origin, no_browser, label))

    def fake_logout(self: CloudOwnerApi, method: str, path: str, *, token: str) -> dict[str, bool]:
        posted.append((method, path, token))
        return {"revoked": True}

    monkeypatch.setattr(cloud_owner_cli, "authorize", fake_authorize)
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: _TOKEN)
    monkeypatch.setattr(cloud_owner_cli, "forget_token", forgotten.append)
    monkeypatch.setattr(CloudOwnerApi, "request", fake_logout)
    runner = CliRunner()
    result = runner.invoke(app, ["cloud", "authorize", "--no-browser", "--label", "Lab PC"])
    assert result.exit_code == 0, result.output
    assert approved == [(_ORIGIN, True, "Lab PC")]

    result = runner.invoke(app, ["cloud", "logout"])
    assert result.exit_code == 0, result.output
    assert posted == [("POST", "/api/owner/v1/logout", _TOKEN)]
    assert forgotten == [_ORIGIN]
    assert "Projects and devices are unchanged" in result.output

    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: None)
    result = runner.invoke(app, ["cloud", "logout"])
    assert result.exit_code == 0, result.output
    assert "already disconnected" in result.output
    assert len(posted) == 1


def test_cli_logout_requires_server_revoke_before_forgetting_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    deleted: list[str] = []
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: _TOKEN)
    monkeypatch.setattr(cloud_owner_cli, "forget_token", deleted.append)
    monkeypatch.setattr(
        CloudOwnerApi,
        "request",
        lambda _self, _method, _path, *, token: {"revoked": False},
    )
    result = CliRunner().invoke(app, ["cloud", "logout"])
    assert result.exit_code != 0
    assert "did not confirm" in result.output
    assert deleted == []


def test_cli_authorization_failure_is_actionable_without_leaking_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise CloudManagementError("Owner confirmation was denied.")

    monkeypatch.setattr(cloud_owner_cli, "authorize", fail)
    result = CliRunner().invoke(app, ["cloud", "authorize"])
    assert result.exit_code != 0
    assert "Owner confirmation was denied" in result.output


def test_cloud_project_list_skips_invalid_server_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cloud_owner_cli,
        "_request",
        lambda *_args, **_kw: {
            "devices": [
                None,
                "incorrect",
                {"id": "offline-device", "projects": [None, "bad", {"id": "good", "alias": "PCB"}]},
                {"id": "no-projects", "alias": "Empty", "projects": []},
            ]
        },
    )
    result = CliRunner().invoke(app, ["cloud", "projects", "--cloud", "--json"])
    assert result.exit_code == 0, result.output
    assert '"good"' in result.output
    assert "incorrect" not in result.output


def test_authorize_existing_token_does_not_reissue_credentials(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _origin: _TOKEN)
    calls: list[str] = []

    def approved_api(
        self: CloudOwnerApi, method: str, path: str, *, token: str
    ) -> dict[str, object]:
        assert method == "GET"
        assert token == _TOKEN
        calls.append(path)
        return {"devices": []}

    monkeypatch.setattr(CloudOwnerApi, "request", approved_api)
    cloud_owner_management.authorize(_ORIGIN, no_browser=True)
    assert calls == ["/api/owner/v1/devices"]
    assert "already connected" in capsys.readouterr().out


def test_owner_api_invalid_approval_url_never_launches_browser_or_saves_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _origin: None)
    monkeypatch.setattr(
        cloud_owner_management.webbrowser,
        "open",
        lambda *_args, **_kwargs: pytest.fail("untrusted URL must not open"),
    )
    monkeypatch.setattr(
        cloud_owner_management,
        "save_token",
        lambda *_args, **_kwargs: pytest.fail("must not save token"),
    )
    monkeypatch.setattr(
        CloudOwnerApi,
        "request",
        lambda _self, _method, _path, **_kw: {
            "status": "pending",
            "approveUrl": "https://attacker.invalid/steal",
        },
    )
    with pytest.raises(CloudManagementError, match="untrusted approval destination"):
        cloud_owner_management.authorize(_ORIGIN, no_browser=False)


@pytest.mark.parametrize("status", ["denied", "expired", "claimed", "mystery"])
def test_owner_api_browser_rejection_is_not_a_session(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    request_id = "Z" * 43
    monkeypatch.setattr(cloud_owner_management.secrets, "token_urlsafe", lambda _: request_id)
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _origin: None)
    monkeypatch.setattr(
        cloud_owner_management,
        "save_token",
        lambda *_args, **_kwargs: pytest.fail("rejected login must not save"),
    )

    def reject(self: CloudOwnerApi, method: str, path: str, *, payload=None, token=None):
        if path.endswith("/start"):
            return {
                "status": "pending",
                "approveUrl": _ORIGIN + "/api/owner/cli/approve?request_id=" + request_id,
            }
        return {"status": status}

    monkeypatch.setattr(CloudOwnerApi, "request", reject)
    with pytest.raises(CloudManagementError, match="approval|Unexpected"):
        cloud_owner_management.authorize(_ORIGIN, no_browser=True)


@pytest.mark.skipif(os.name != "nt", reason="Windows per-user credential-vault contract")
def test_windows_management_token_roundtrip_uses_only_current_user_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_credentials

    credentials: dict[tuple[str, str], bytes] = {}
    seen: list[str] = []

    def get(record: str, part: str) -> bytes | None:
        seen.append("read:" + part)
        return credentials.get((record, part))

    def create(record: str, part: str, value: bytes) -> None:
        assert part == "owner_api"
        assert (record, part) not in credentials
        credentials[(record, part)] = value
        seen.append("create:" + part)

    def delete(record: str, part: str) -> bool:
        seen.append("delete:" + part)
        return credentials.pop((record, part), None) is not None

    monkeypatch.setattr(cloud_windows_credentials, "read_credential", get)
    monkeypatch.setattr(cloud_windows_credentials, "create_credential", create)
    monkeypatch.setattr(cloud_windows_credentials, "delete_credential", delete)
    assert cloud_owner_management.load_token(_ORIGIN) is None
    cloud_owner_management.save_token(_ORIGIN, _TOKEN)
    assert cloud_owner_management.load_token(_ORIGIN) == _TOKEN
    assert len(credentials) == 1
    assert "owner_api" in next(iter(credentials))
    # Re-approval replaces this account-scoped slot, not another service.
    cloud_owner_management.save_token(_ORIGIN, "kmpc1_" + "b" * 43)
    assert cloud_owner_management.load_token(_ORIGIN) == "kmpc1_" + "b" * 43
    cloud_owner_management.forget_token(_ORIGIN)
    assert cloud_owner_management.load_token(_ORIGIN) is None
    assert credentials == {}
    assert seen.count("create:owner_api") == 2
    assert seen.count("delete:owner_api") == 2


def test_cloud_management_request_denies_malformed_success_responses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Reply:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self, _cap: int) -> bytes:
            return self.body

        def release_conn(self) -> None:
            pass

    class Pool:
        def __init__(self, raw: bytes) -> None:
            self.raw = raw

        def request(self, *_args: object, **_kwargs: object) -> Reply:
            return Reply(self.raw)

        def clear(self) -> None:
            pass

    for raw in (b"", b"[]", b'{"broken":', b'"not an object"', b"x" * 65_537):
        monkeypatch.setattr(
            cloud_owner_management.urllib3,
            "PoolManager",
            lambda raw=raw, **_kwargs: Pool(raw),
        )
        with pytest.raises(CloudManagementError):
            CloudOwnerApi(_ORIGIN).request("GET", "/api/owner/v1/devices")


def test_cloud_owner_authorize_fails_cleanly_when_browser_open_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id = "Z" * 43
    monkeypatch.setattr(cloud_owner_management.secrets, "token_urlsafe", lambda _: request_id)
    monkeypatch.setattr(cloud_owner_management, "load_token", lambda _origin: None)
    monkeypatch.setattr(
        cloud_owner_management.webbrowser,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("headless browser")),
    )

    def stub(self: CloudOwnerApi, method: str, path: str, *, payload=None, token=None):
        if path.endswith("/start"):
            return {
                "status": "pending",
                "approveUrl": _ORIGIN + "/api/owner/cli/approve?request_id=" + request_id,
            }
        return {"status": "expired"}

    monkeypatch.setattr(CloudOwnerApi, "request", stub)
    with pytest.raises(CloudManagementError, match="approval"):
        cloud_owner_management.authorize(_ORIGIN)


def test_cloud_owner_api_rejects_malformed_token_and_unsupported_paths() -> None:
    api = CloudOwnerApi(_ORIGIN)
    with pytest.raises(CloudManagementError, match="Unsupported"):
        api.request("POST", "/api/owner/../../foreign", token=_TOKEN)
    with pytest.raises(CloudManagementError, match="Unsupported"):
        api.request("PUT", "/api/owner/v1/devices", token=_TOKEN)
    with pytest.raises(CloudManagementError, match="invalid"):
        api.request("GET", "/api/owner/v1/devices", token=_TOKEN[:10])
    with pytest.raises(CloudManagementError, match="valid"):
        cloud_owner_management.save_token(_ORIGIN, "invalid")
