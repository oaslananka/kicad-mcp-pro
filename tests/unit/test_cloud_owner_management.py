"""CLI management is owner-approved, token-scoped and no-redirect; no live Cloud calls."""

from __future__ import annotations

import json
import os
from pathlib import Path

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
    tls_settings: list[dict[str, object]] = []

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

    def secure_pool(**kwargs: object) -> FakePool:
        tls_settings.append(kwargs)
        return FakePool()

    monkeypatch.setattr(cloud_owner_management.urllib3, "PoolManager", secure_pool)
    answer = CloudOwnerApi(_ORIGIN).request("GET", "/api/owner/v1/devices", token=_TOKEN)
    assert len(tls_settings) == 1
    assert tls_settings[0]["cert_reqs"] == "CERT_REQUIRED"
    assert tls_settings[0]["retries"] is False
    assert "ssl_context" not in tls_settings[0]
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
    # This contract test must not stop the runner machine's real Connector.
    monkeypatch.setattr(cloud_owner_cli, "_disconnect_local_cloud_device", lambda _origin: False)
    runner = CliRunner()
    result = runner.invoke(app, ["cloud", "authorize", "--no-browser", "--label", "Lab PC"])
    assert result.exit_code == 0, result.output
    assert approved == [(_ORIGIN, True, "Lab PC")]

    result = runner.invoke(app, ["cloud", "logout"])
    assert result.exit_code == 0, result.output
    assert posted == [("POST", "/api/owner/v1/logout", _TOKEN)]
    assert forgotten == [_ORIGIN]
    assert "Cloud CLI logged out." in result.output
    assert "No same-Cloud local device was connected." in result.output

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
        cloud_owner_cli,
        "_disconnect_local_cloud_device",
        lambda _origin: True,
    )
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


def test_cloud_add_project_registers_second_project_and_keeps_file_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver, cloud_windows_connector

    directory = tmp_path / "KiCad Projects" / "Motor Controller"
    directory.mkdir(parents=True)
    project_file = directory / "motor.kicad_pro"
    project_file.write_text("OWNER_PRIVATE_FILE", encoding="utf-8")
    binding_file = tmp_path / "local-bindings.json"
    cloud_id = "7d81dc49-8adc-4c52-9224-52d4b74fc543"
    device_id = "7ddbf90b-4a3c-4d5f-86e5-74a074e2e598"
    device = SimpleNamespace(origin=_ORIGIN, device_id=device_id)
    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: device)
    monkeypatch.setattr(cloud_folder_browse_receiver, "default_bindings_file", lambda: binding_file)
    requests: list[tuple[str, str, object]] = []

    def fake_cloud(self: CloudOwnerApi, method: str, route: str, *, payload: dict[str, object]):
        requests.append((method, route, payload))
        return {"id": cloud_id}

    monkeypatch.setattr(CloudOwnerApi, "authorized", fake_cloud)
    result = cloud_owner_cli._add_project_on_paired_device(
        _ORIGIN, directory, filename=None, name=None
    )
    assert result == (cloud_id, "Motor Controller")
    assert requests == [
        ("POST", "/api/owner/v1/projects", {"deviceId": device_id, "alias": "Motor Controller"})
    ]
    assert binding_file.is_file()
    saved = binding_file.read_text(encoding="utf-8")
    assert cloud_id in saved
    assert json.loads(saved)[cloud_id] == str(project_file)
    assert project_file.read_text(encoding="utf-8") == "OWNER_PRIVATE_FILE"


def test_add_project_folder_with_multiple_files_requires_explicit_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver, cloud_windows_connector

    folder = tmp_path / "my boards"
    folder.mkdir()
    for stem in ("first", "second"):
        (folder / f"{stem}.kicad_pro").write_text("PRIVATE", encoding="utf-8")
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=_ORIGIN, device_id="7ddbf90b-4a3c-4d5f-86e5-74a074e2e598"),
    )
    monkeypatch.setattr(
        cloud_folder_browse_receiver, "default_bindings_file", lambda: tmp_path / "bindings.json"
    )
    requested: list[dict[str, object]] = []

    def cloud(self: CloudOwnerApi, method: str, path: str, *, payload: dict[str, object]):
        requested.append(payload)
        return {"id": "7d81dc49-8adc-4c52-9224-52d4b74fc543"}

    monkeypatch.setattr(CloudOwnerApi, "authorized", cloud)
    with pytest.raises(CloudManagementError, match="--file"):
        cloud_owner_cli._add_project_on_paired_device(_ORIGIN, folder, filename=None, name=None)
    assert requested == []
    project_id, label = cloud_owner_cli._add_project_on_paired_device(
        _ORIGIN, folder, filename="second.kicad_pro", name="Chosen board"
    )
    assert project_id == "7d81dc49-8adc-4c52-9224-52d4b74fc543"
    assert label == "Chosen board"
    content = (tmp_path / "bindings.json").read_text(encoding="utf-8")
    assert "second.kicad_pro" in content
    assert "first.kicad_pro" not in content
    assert all((folder / f"{stem}.kicad_pro").is_file() for stem in ("first", "second"))


def test_add_project_local_bind_failure_removes_only_new_cloud_record(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import (
        cloud_folder_browse_receiver,
        cloud_local_folder_browser,
        cloud_windows_connector,
    )

    folder = tmp_path / "board"
    folder.mkdir()
    (folder / "board.kicad_pro").write_text("PRIVATE", encoding="utf-8")
    cloud_id = "7d81dc49-8adc-4c52-9224-52d4b74fc543"
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=_ORIGIN, device_id="7ddbf90b-4a3c-4d5f-86e5-74a074e2e598"),
    )
    monkeypatch.setattr(
        cloud_folder_browse_receiver, "default_bindings_file", lambda: tmp_path / "bindings.json"
    )
    monkeypatch.setattr(cloud_local_folder_browser.LocalFolderBrowser, "bind", lambda *_args: False)
    actions: list[str] = []

    def post(self: CloudOwnerApi, method: str, route: str, *, payload: dict[str, object]):
        actions.append(route)
        return {"id": cloud_id} if route.endswith("/projects") else {"removed": True}

    monkeypatch.setattr(CloudOwnerApi, "authorized", post)
    with pytest.raises(CloudManagementError, match="Cloud record was removed"):
        cloud_owner_cli._add_project_on_paired_device(_ORIGIN, folder, filename=None, name=None)
    assert actions == ["/api/owner/v1/projects", "/api/owner/v1/projects/remove"]
    assert (folder / "board.kicad_pro").read_text(encoding="utf-8") == "PRIVATE"


def test_add_project_does_not_create_cloud_record_without_paired_device(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp import cloud_windows_connector

    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: None)
    monkeypatch.setattr(
        CloudOwnerApi,
        "authorized",
        lambda *_args, **_kw: pytest.fail("No orphan project must be created"),
    )
    with pytest.raises(CloudManagementError, match="Pair this computer"):
        cloud_owner_cli._add_project_on_paired_device(_ORIGIN, tmp_path, filename=None, name=None)


def test_cloud_add_project_command_accepts_folder_path_without_pairing_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="nt"))
    project_id = "7d81dc49-8adc-4c52-9224-52d4b74fc543"
    called: list[tuple[str, Path, str | None, str | None]] = []

    def add(origin: str, path: Path, *, filename: str | None, name: str | None):
        called.append((origin, path, filename, name))
        return project_id, "Motor Controller"

    monkeypatch.setattr(cloud_owner_cli, "_add_project_on_paired_device", add)
    result = CliRunner().invoke(app, ["cloud", "add-project", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert called == [(_ORIGIN, tmp_path, None, None)]
    assert project_id in result.output
    assert "registered and bound locally" in result.output


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ("different-owner", "different Cloud site"),
        ("file-instead-of-folder", "project folder"),
        ("missing-path", "unavailable"),
        ("empty-folder", "no selectable KiCad project"),
        ("empty-name", "project name"),
        ("symbolic-link", "not a link"),
    ],
)
def test_cloud_add_project_refuses_invalid_folder_or_device_before_cloud_mutation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str, message: str
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver, cloud_windows_connector

    folder = tmp_path / "Board Folder"
    folder.mkdir()
    project_file = folder / "board.kicad_pro"
    project_file.write_text("KEEP_PRIVATE", encoding="utf-8")
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(
            origin="https://another-cloud.example" if failure == "different-owner" else _ORIGIN,
            device_id="7ddbf90b-4a3c-4d5f-86e5-74a074e2e598",
        ),
    )
    monkeypatch.setattr(
        cloud_folder_browse_receiver,
        "default_bindings_file",
        lambda: tmp_path / "never-created.json",
    )
    monkeypatch.setattr(
        CloudOwnerApi,
        "authorized",
        lambda *_args, **_kwargs: pytest.fail("Invalid path must not create a Cloud project"),
    )
    selected: Path = folder
    if failure == "file-instead-of-folder":
        selected = project_file
    elif failure == "missing-path":
        selected = tmp_path / "not-present"
    elif failure == "empty-folder":
        selected = tmp_path / "Empty"
        selected.mkdir()
    elif failure == "symbolic-link":
        original = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == folder or original(self),
        )
    with pytest.raises(CloudManagementError, match=message):
        cloud_owner_cli._add_project_on_paired_device(
            _ORIGIN,
            selected,
            filename=None,
            name="" if failure == "empty-name" else None,
        )
    assert project_file.read_text(encoding="utf-8") == "KEEP_PRIVATE"
    assert not (tmp_path / "never-created.json").exists()


def test_cloud_add_project_rejects_unconfirmed_cloud_identity_without_binding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_folder_browse_receiver, cloud_windows_connector

    folder = tmp_path / "valid"
    folder.mkdir()
    (folder / "valid.kicad_pro").write_text("PRIVATE", encoding="utf-8")
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=_ORIGIN, device_id="7ddbf90b-4a3c-4d5f-86e5-74a074e2e598"),
    )
    monkeypatch.setattr(
        cloud_folder_browse_receiver,
        "default_bindings_file",
        lambda: tmp_path / "bindings.json",
    )
    monkeypatch.setattr(CloudOwnerApi, "authorized", lambda *_a, **_kw: {"id": None})
    with pytest.raises(CloudManagementError, match="valid project identity"):
        cloud_owner_cli._add_project_on_paired_device(
            _ORIGIN,
            folder,
            filename=None,
            name=None,
        )
    assert not (tmp_path / "bindings.json").exists()


def test_failed_cloud_project_registration_rollback_reports_manual_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import (
        cloud_folder_browse_receiver,
        cloud_local_folder_browser,
        cloud_windows_connector,
    )

    folder = tmp_path / "board"
    folder.mkdir()
    (folder / "board.kicad_pro").write_text("PRIVATE", encoding="utf-8")
    cid = "7d81dc49-8adc-4c52-9224-52d4b74fc543"
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=_ORIGIN, device_id="7ddbf90b-4a3c-4d5f-86e5-74a074e2e598"),
    )
    monkeypatch.setattr(
        cloud_folder_browse_receiver, "default_bindings_file", lambda: tmp_path / "bindings.json"
    )
    monkeypatch.setattr(cloud_local_folder_browser.LocalFolderBrowser, "bind", lambda *_: False)
    calls: list[str] = []

    def fail_rollback(self: CloudOwnerApi, method: str, route: str, *, payload: dict[str, object]):
        calls.append(route)
        if route.endswith("/remove"):
            raise CloudManagementError("Cloud disconnected")
        return {"id": cid}

    monkeypatch.setattr(CloudOwnerApi, "authorized", fail_rollback)
    with pytest.raises(CloudManagementError, match="rollback could not be confirmed") as error:
        cloud_owner_cli._add_project_on_paired_device(_ORIGIN, folder, filename=None, name=None)
    assert cid in str(error.value)
    assert calls == ["/api/owner/v1/projects", "/api/owner/v1/projects/remove"]
    assert (folder / "board.kicad_pro").read_text(encoding="utf-8") == "PRIVATE"


def test_cloud_add_project_command_rejects_non_windows_and_surfaces_local_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="posix"))
    result = CliRunner().invoke(app, ["cloud", "add-project", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "requires a paired Windows device" in result.output

    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="nt"))

    def denied(*_args: object, **_kwargs: object) -> tuple[str, str]:
        raise CloudManagementError("Select one KiCad project with --file.")

    monkeypatch.setattr(cloud_owner_cli, "_add_project_on_paired_device", denied)
    result = CliRunner().invoke(app, ["cloud", "add-project", "--path", str(tmp_path)])
    assert result.exit_code != 0
    assert "Select one KiCad project with --file." in result.output


def test_cli_logout_disables_local_connector_after_cloud_token_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: _TOKEN)
    monkeypatch.setattr(
        CloudOwnerApi,
        "request",
        lambda _self, _method, _path, *, token: (
            events.append("remote-revoked") or {"revoked": True}
        ),
    )
    monkeypatch.setattr(
        cloud_owner_cli,
        "forget_token",
        lambda _origin: events.append("token-forgotten"),
    )
    monkeypatch.setattr(
        cloud_owner_cli,
        "_disconnect_local_cloud_device",
        lambda _origin: events.append("device-stopped") or True,
    )
    response = CliRunner().invoke(app, ["cloud", "logout"])
    assert response.exit_code == 0, response.output
    assert events == ["device-stopped", "remote-revoked", "token-forgotten"]
    assert "Local Connector stopped" in response.output
    assert "device pairing and KiCad projects preserved" in response.output


def test_logout_without_management_token_still_disables_local_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: None)
    monkeypatch.setattr(CloudOwnerApi, "request", lambda *_a, **_kw: pytest.fail("No token"))
    monkeypatch.setattr(
        cloud_owner_cli,
        "_disconnect_local_cloud_device",
        lambda _origin: True,
    )
    response = CliRunner().invoke(app, ["cloud", "logout"])
    assert response.exit_code == 0, response.output
    assert "Local Connector stopped" in response.output
    assert "No active CLI token." in response.output


def test_windows_logout_only_stops_device_for_matching_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_windows_connector, cloud_windows_task_scheduler

    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="nt"))
    selected = SimpleNamespace(origin="https://other.example", device_id="foreign")
    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: selected)
    events: list[str] = []
    monkeypatch.setattr(
        cloud_windows_task_scheduler,
        "disable_windows_connector",
        lambda: events.append("disabled") or True,
    )
    assert cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN) is False
    assert events == []
    selected.origin = _ORIGIN
    assert cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN) is True
    assert events == ["disabled"]


def test_windows_logout_unverified_connector_stop_is_not_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_windows_connector, cloud_windows_task_scheduler

    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=_ORIGIN),
    )
    monkeypatch.setattr(
        cloud_windows_task_scheduler,
        "disable_windows_connector",
        lambda: False,
    )
    with pytest.raises(CloudManagementError, match="not confirmed"):
        cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN)


def test_linux_logout_stops_only_registered_same_cloud_service(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_local_registry, cloud_managed_connector, cloud_registered_pilot

    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(cloud_owner_cli, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(cloud_local_registry, "default_registry_root", lambda: tmp_path)
    record = {"cloudOrigin": "https://other-cloud.example"}
    monkeypatch.setattr(cloud_registered_pilot, "_single_registered_identity", lambda _: record)
    stopped: list[str] = []
    monkeypatch.setattr(
        cloud_managed_connector,
        "_disable",
        lambda: stopped.append("service") or 0,
    )
    assert cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN) is False
    assert stopped == []
    record["cloudOrigin"] = _ORIGIN
    assert cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN) is True
    assert stopped == ["service"]


def test_linux_logout_does_not_claim_success_when_service_stop_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_local_registry, cloud_managed_connector, cloud_registered_pilot

    (tmp_path / "projects").mkdir()
    monkeypatch.setattr(cloud_owner_cli, "os", SimpleNamespace(name="posix"))
    monkeypatch.setattr(cloud_owner_cli, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(cloud_local_registry, "default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(
        cloud_registered_pilot,
        "_single_registered_identity",
        lambda _: {"cloudOrigin": _ORIGIN},
    )
    monkeypatch.setattr(cloud_managed_connector, "_disable", lambda: 1)
    with pytest.raises(CloudManagementError, match="not confirmed"):
        cloud_owner_cli._disconnect_local_cloud_device(_ORIGIN)


def test_logout_network_failure_still_revokes_local_device_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: _TOKEN)
    monkeypatch.setattr(
        cloud_owner_cli,
        "_disconnect_local_cloud_device",
        lambda _origin: events.append("local-off") or True,
    )
    monkeypatch.setattr(
        CloudOwnerApi,
        "request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CloudManagementError("Cloud unreachable, retry logout")
        ),
    )
    monkeypatch.setattr(
        cloud_owner_cli,
        "forget_token",
        lambda _origin: pytest.fail("unrevoked Cloud token must remain for retry"),
    )
    response = CliRunner().invoke(app, ["cloud", "logout"])
    assert response.exit_code != 0
    assert "Cloud unreachable" in response.output
    assert events == ["local-off"]


def test_logout_remote_revocation_continues_after_unverified_local_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    monkeypatch.setattr(cloud_owner_cli, "load_token", lambda _origin: _TOKEN)

    def local_failure(_origin: str) -> bool:
        events.append("local-stop-failed")
        raise CloudManagementError("local device shutdown was not confirmed")

    monkeypatch.setattr(cloud_owner_cli, "_disconnect_local_cloud_device", local_failure)
    monkeypatch.setattr(
        CloudOwnerApi,
        "request",
        lambda *_args, **_kw: events.append("remote-revoked") or {"revoked": True},
    )
    monkeypatch.setattr(
        cloud_owner_cli,
        "forget_token",
        lambda _origin: events.append("local-token-forgotten"),
    )
    result = CliRunner().invoke(app, ["cloud", "logout"])
    assert result.exit_code != 0
    assert "not confirmed" in result.output
    assert events == ["local-stop-failed", "remote-revoked", "local-token-forgotten"]
