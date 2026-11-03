"""No real login, device enrollment, key or service change in CLI command tests."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from kicad_mcp.server import app


def test_login_opens_only_first_party_browser_and_saves_no_local_token(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open", lambda url, **_kwargs: seen.append(url) or True
    )
    result = CliRunner().invoke(app, ["cloud", "login"])
    assert result.exit_code == 0, result.output
    assert seen == ["https://kicad-mcp-pro.oaslananka.dev/sign-in"]
    assert "Browser login does not grant device or project access." in result.output
    assert "cloud connect" in result.output


def test_login_headless_prints_link_but_never_launches_browser(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kw: pytest.fail("no browser expected"),
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "https://kicad-mcp-pro.oaslananka.dev/sign-in" in result.output


@pytest.mark.parametrize(
    "origin",
    [
        "http://kicad-mcp-pro.oaslananka.dev",
        "https://user:password@site.example",
        "https://site.example/path",
        "https://site.example?token=secret",
        "https://site.example/#fragment",
        "javascript:alert(1)",
    ],
)
def test_cloud_login_rejects_unsafe_origins_without_opening_browser(
    monkeypatch, origin: str
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kw: pytest.fail("invalid origin"),
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--cloud-origin", origin])
    assert result.exit_code != 0


def test_cloud_connect_reuses_existing_signed_pairing_flow(monkeypatch, tmp_path) -> None:
    called: list[list[str]] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path / "unregistered"
    )
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: called.append(args) or 0)
    result = CliRunner().invoke(app, ["cloud", "connect", "--alias", "Lab board"])
    assert result.exit_code == 0, result.output
    assert called == [
        [
            "--cloud-origin",
            "https://kicad-mcp-pro.oaslananka.dev",
            "--alias",
            "Lab board",
            "--begin-pairing",
        ]
    ]
    assert "does not enable the persistent Connector" in result.output


@pytest.mark.parametrize("command", ["status", "enable", "disable"])
def test_cloud_connector_commands_delegate_to_existing_owner_managed_boundary(
    monkeypatch, command: str
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.main", lambda args: calls.append(args) or 0
    )
    result = CliRunner().invoke(app, ["cloud", command])
    assert result.exit_code == 0, result.output
    assert calls == [[command]]


def test_cloud_connect_does_not_pair_an_already_registered_project(monkeypatch, tmp_path) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev"},
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("must not re-enroll an existing project"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code == 0, result.output
    assert "Cloud enrollment has NOT been verified" in result.output
    assert "cloud connect --new-device" in result.output
    assert "existing local registration and keys were not changed" in result.output


def test_cloud_connect_rejects_ambiguous_registration_before_enrollment(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("fixture", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)

    def invalid(_root):
        raise ValueError("ambiguous project")

    monkeypatch.setattr("kicad_mcp.cloud_registered_pilot._single_registered_identity", invalid)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("ambiguous registration cannot trigger new key"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "Existing Cloud registration needs local repair" in result.output


def test_cloud_connect_explicit_new_device_preserves_existing_local_registration(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    projects = registry / "projects"
    projects.mkdir(parents=True)
    existing = projects / "fixture.json"
    existing.write_text("private-existing-record", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev"},
    )
    called: list[list[str]] = []
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: called.append(args) or 0)
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device"])
    assert result.exit_code == 0, result.output
    assert len(called) == 1
    assert called[0][-1] == "--begin-pairing"
    assert existing.read_text(encoding="utf-8") == "private-existing-record"
    assert "Existing registration and keys will be preserved" in result.output
    assert "local project registry must also reference that new" in result.output


def test_cloud_connect_new_device_rejects_corrupt_existing_registration(
    monkeypatch, tmp_path
) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("untrusted", encoding="utf-8")
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: (_ for _ in ()).throw(ValueError("corrupt")),
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda _args: pytest.fail("corrupt existing registration must fail closed"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device"])
    assert result.exit_code != 0
    assert "Existing Cloud registration needs local repair" in result.output


def test_login_browser_launch_exception_prints_link(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("desktop offline")),
    )
    result = CliRunner().invoke(app, ["cloud", "login"])
    assert result.exit_code == 0
    assert "Open the link above in your preferred browser" in result.output


@pytest.mark.parametrize("alias", ["", "x" * 81, "control\nchar"])
def test_connect_rejects_invalid_alias_without_pairing(monkeypatch, alias) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("invalid alias cannot start pairing"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect", "--alias", alias])
    assert result.exit_code != 0


def test_setup_performs_one_command_onboarding(monkeypatch, tmp_path) -> None:
    proj_dir = tmp_path / "my_board"
    proj_dir.mkdir()
    (proj_dir / "my_board.kicad_pro").write_text("", encoding="utf-8")

    cloud_root = tmp_path / "cloud_registry"
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: cloud_root)

    dev_id = "11111111-1111-4111-8111-111111111111"
    proj_id = "22222222-2222-4222-8222-222222222222"

    def mock_enroll(_origin, _alias, keyfile, approval):
        approval("https://kicad-mcp-pro.oaslananka.dev/devices/pairing", "chal-1", "ABCDEF-123456")
        return dev_id, "0" * 64

    monkeypatch.setattr("kicad_mcp.cloud_pair.enroll", mock_enroll)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._read_owner_binding",
        lambda _kf: {
            "origin": "https://kicad-mcp-pro.oaslananka.dev",
            "deviceId": dev_id,
            "fingerprint": "0" * 64,
            "ownerSub": "github|test-owner",
        },
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.register_device_project",
        lambda _origin, _kf, alias: {
            "projectId": proj_id,
            "alias": alias,
            "ownerSub": "github|test-owner",
            "enabled": True,
        },
    )

    enable_called = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector._enable", lambda: enable_called.append(1)
    )
    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._status", lambda: "Connected")

    result = CliRunner().invoke(
        app,
        ["cloud", "setup", "--project-dir", str(proj_dir), "--no-browser"],
    )
    assert result.exit_code == 0, result.output
    assert "KiCad MCP Pro Cloud Setup Complete!" in result.output
    assert dev_id in result.output
    assert proj_id in result.output
    assert len(enable_called) == 1

    # Verify project record written
    record_file = cloud_root / "projects" / f"{proj_id}.json"
    assert record_file.is_file()
    import json

    data = json.loads(record_file.read_text(encoding="utf-8"))
    assert data["deviceId"] == dev_id
    assert data["projectId"] == proj_id
    assert data["filenameStem"] == "my_board"
    assert data["ownerSub"] == "github|test-owner"


def test_setup_existing_valid_registration_reconnects(monkeypatch, tmp_path) -> None:
    cloud_root = tmp_path / "cloud_registry"
    projects_dir = cloud_root / "projects"
    keys_dir = cloud_root / "keys"
    projects_dir.mkdir(parents=True)
    keys_dir.mkdir(parents=True)

    proj_id = "33333333-3333-4333-8333-333333333333"
    slot_id = "44444444-4444-4444-8444-444444444444"
    (keys_dir / f"{slot_id}.pem").write_text("dummy-key", encoding="utf-8")
    (projects_dir / f"{proj_id}.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: cloud_root)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {
            "ownerSub": "github|test-owner",
            "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
            "deviceId": "55555555-5555-4555-8555-555555555555",
            "projectId": proj_id,
            "keySlot": slot_id,
            "directory": str(tmp_path / "test"),
            "filenameStem": "test",
        },
    )

    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.enroll",
        lambda *_args: pytest.fail("Must not re-enroll existing device"),
    )

    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._status", lambda: "Connected")

    result = CliRunner().invoke(app, ["cloud", "setup", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "Found valid existing Cloud device and project registration" in result.output
    assert proj_id in result.output


def test_setup_handles_pairing_error(monkeypatch, tmp_path) -> None:
    from kicad_mcp.cloud_pair import CloudPairingError

    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path / "cloud"
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.enroll",
        lambda *_args: (_ for _ in ()).throw(CloudPairingError("denied")),
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--no-browser"])
    assert result.exit_code != 0
    assert "Device pairing failed or was denied" in result.output


def test_projects_command_empty_and_populated(monkeypatch, tmp_path) -> None:
    cloud_root = tmp_path / "cloud"
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: cloud_root)

    # Empty
    res1 = CliRunner().invoke(app, ["cloud", "projects"])
    assert res1.exit_code == 0
    assert "No local KiCad projects currently registered" in res1.output

    # Populated
    projects_dir = cloud_root / "projects"
    projects_dir.mkdir(parents=True)
    (projects_dir / "fixture.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda _root: {
            "ownerSub": "sub",
            "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
            "deviceId": "dev-1",
            "projectId": "proj-1",
            "keySlot": "slot-1",
            "directory": "/path/to/board",
            "filenameStem": "board",
        },
    )

    # Archived project
    archive_dir = cloud_root / "archived-project-registrations"
    archive_dir.mkdir(parents=True)
    import json

    (archive_dir / "old-proj.json").write_text(
        json.dumps(
            {
                "ownerSub": "sub",
                "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
                "deviceId": "dev-0",
                "projectId": "old-proj-id",
                "keySlot": "slot-0",
                "directory": "/path/to/old",
                "filenameStem": "old_board",
            }
        ),
        encoding="utf-8",
    )

    res2 = CliRunner().invoke(app, ["cloud", "projects"])
    assert res2.exit_code == 0
    assert "Active Registered Project:" in res2.output
    assert "board" in res2.output
    assert "Archived Projects (1):" in res2.output
    assert "old_board" in res2.output


@pytest.mark.parametrize(
    "cmd,expected_arg",
    [
        ("disconnect", "disable"),
        ("reconnect", "enable"),
        ("run", "run"),
    ],
)
def test_cloud_companion_commands_delegate(monkeypatch, cmd: str, expected_arg: str) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.main", lambda args: calls.append(args) or 0
    )
    result = CliRunner().invoke(app, ["cloud", cmd])
    assert result.exit_code == 0, result.output
    assert calls == [[expected_arg]]
