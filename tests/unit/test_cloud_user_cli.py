"""No real login, device enrollment, key or service change in CLI command tests."""

from __future__ import annotations

import os
from pathlib import Path

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


def test_find_kicad_project_edge_cases(tmp_path: Path) -> None:
    import typer

    from kicad_mcp.cloud_user_cli import _discover_kicad_project

    # Not a directory
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("test")
    with pytest.raises(typer.BadParameter, match="Project path is not a directory"):
        _discover_kicad_project(not_a_dir)

    # Only .kicad_sch
    dir_sch = tmp_path / "sch_only"
    dir_sch.mkdir()
    (dir_sch / "schematic.kicad_sch").touch()
    assert _discover_kicad_project(dir_sch) == (dir_sch.resolve(), "schematic")

    # Only .kicad_pcb
    dir_pcb = tmp_path / "pcb_only"
    dir_pcb.mkdir()
    (dir_pcb / "layout.kicad_pcb").touch()
    assert _discover_kicad_project(dir_pcb) == (dir_pcb.resolve(), "layout")

    # Subfolder with .kicad_pro
    dir_sub = tmp_path / "nested"
    dir_sub.mkdir()
    sub_child = dir_sub / "child"
    sub_child.mkdir()
    (sub_child / "board.kicad_pro").touch()
    assert _discover_kicad_project(dir_sub) == (sub_child.resolve(), "board")

    # Empty dir fallback
    dir_empty = tmp_path / "empty"
    dir_empty.mkdir()
    assert _discover_kicad_project(dir_empty) == (dir_empty.resolve(), "empty")

    # Non-alphanumeric stem fallback
    dir_special = tmp_path / "---"
    dir_special.mkdir()
    assert _discover_kicad_project(dir_special) == (dir_special.resolve(), "project")


def test_archive_existing_active_collision(tmp_path: Path) -> None:
    from kicad_mcp.cloud_user_cli import _write_project_record

    projects = tmp_path / "projects"
    archive = tmp_path / "archived-project-registrations"
    projects.mkdir(parents=True)
    archive.mkdir(parents=True)

    (projects / "old.json").write_text('{"projectId": "old"}')
    (archive / "old.json").write_text('{"projectId": "older"}')

    record = {"projectId": "new-proj"}
    _write_project_record(tmp_path, record)

    archived_files = list(archive.glob("old*.json"))
    assert len(archived_files) == 2
    assert (projects / "new-proj.json").exists()


def test_setup_invalid_device_alias(tmp_path: Path) -> None:
    args = ["cloud", "setup", "--alias", "inv@lid!", "--project-dir", str(tmp_path)]
    result = CliRunner().invoke(app, args)
    assert result.exit_code != 0
    assert "Device alias must be 1 to 64 alphanumeric characters" in result.output


def test_setup_different_origin_already_registered(tmp_path: Path, monkeypatch) -> None:
    fake_reg = {
        "cloudOrigin": "https://other-cloud.example.com",
        "deviceId": "dev-1",
        "projectId": "proj-1",
        "keySlot": "slot-1",
        "directory": str(tmp_path),
        "filenameStem": "demo",
    }
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / "p.json").touch()
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda root: fake_reg,
    )

    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "A different Cloud origin is already registered" in result.output


def test_setup_oserror_inspect_active(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    projects_dir = tmp_path / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    (projects_dir / "p.json").touch()

    def raise_err(root: Path) -> dict[str, str]:
        raise OSError("Disk read fault")

    monkeypatch.setattr("kicad_mcp.cloud_registered_pilot._single_registered_identity", raise_err)

    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "Existing Cloud registration needs local repair" in result.output


def test_status_with_active_registration(tmp_path: Path, monkeypatch) -> None:
    fake_reg = {
        "cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev",
        "deviceId": "dev-uuid-1234",
        "projectId": "proj-uuid-5678",
        "directory": "/home/user/my_board",
        "filenameStem": "main_pcb",
    }
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda root: fake_reg,
    )
    monkeypatch.setattr("kicad_mcp.cloud_managed_connector.main", lambda args: 0)

    result = CliRunner().invoke(app, ["cloud", "status"])
    assert result.exit_code == 0
    assert "Cloud Origin:    https://kicad-mcp-pro.oaslananka.dev" in result.output
    assert "Device ID:       dev-uuid-1234" in result.output
    assert "Project ID:      proj-uuid-5678" in result.output
    assert "Local Directory: /home/user/my_board (main_pcb)" in result.output


def test_projects_corrupt_archive(tmp_path: Path, monkeypatch) -> None:
    reg_root = tmp_path / "reg"
    projects = reg_root / "projects"
    archive = reg_root / "archived-project-registrations"
    projects.mkdir(parents=True)
    archive.mkdir(parents=True)
    (projects / "p1.json").touch()
    (archive / "corrupted.json").write_text("not-valid-json")

    fake_reg = {
        "filenameStem": "board",
        "projectId": "pid",
        "directory": "/path",
        "deviceId": "did",
        "cloudOrigin": "https://example.com",
    }
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: reg_root)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity",
        lambda root: fake_reg,
    )
    result = CliRunner().invoke(app, ["cloud", "projects"])
    assert result.exit_code == 0
    assert "corrupted.json" in result.output


def test_cloud_pair_main(tmp_path: Path, monkeypatch) -> None:
    import kicad_mcp.cloud_pair as cloud_pair

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(cloud_pair, "default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(cloud_pair, "_open_owner_private_dir", lambda path: 999)
    monkeypatch.setattr("os.close", lambda fd: None)
    monkeypatch.setattr(
        cloud_pair, "enroll", lambda origin, alias, keyfile, approval: ("dev-1", "fp-1")
    )

    ret = cloud_pair.main(
        [
            "--cloud-origin",
            "https://kicad-mcp-pro.oaslananka.dev",
            "--alias",
            "test-device",
            "--begin-pairing",
        ]
    )
    assert ret == 0

    def raise_interrupt(*args: object) -> None:
        raise KeyboardInterrupt()

    monkeypatch.setattr(cloud_pair, "enroll", raise_interrupt)
    ret_err = cloud_pair.main(
        [
            "--cloud-origin",
            "https://kicad-mcp-pro.oaslananka.dev",
            "--alias",
            "test-device",
            "--begin-pairing",
        ]
    )
    assert ret_err == 1


def test_cloud_pair_keys_owner_sub_validation(tmp_path: Path) -> None:
    from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _save_owner_binding

    keyfile = tmp_path / "test.pem"
    keyfile.write_text("dummy-pem")

    uuid_str = "00000000-0000-4000-8000-000000000000"
    with pytest.raises(LocalApprovalDeniedError):
        _save_owner_binding(
            keyfile,
            origin="https://example.com",
            device_id=uuid_str,
            fingerprint="fp",
            owner_sub=123,  # type: ignore
        )

    with pytest.raises(LocalApprovalDeniedError):
        _save_owner_binding(
            keyfile,
            origin="https://example.com",
            device_id=uuid_str,
            fingerprint="fp",
            owner_sub="x" * 300,
        )


def test_setup_browser_approval_and_service_fallback(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "board.kicad_pro").touch()
    keys_dir = tmp_path / "keys"
    projects_dir = tmp_path / "projects"
    keys_dir.mkdir(parents=True)
    projects_dir.mkdir(parents=True)

    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    monkeypatch.setattr("kicad_mcp.cloud_pair.default_registry_root", lambda: tmp_path)

    browser_opened: list[str] = []

    def mock_open(url: str, **kwargs: object) -> bool:
        browser_opened.append(url)
        return True

    monkeypatch.setattr("webbrowser.open", mock_open)

    def mock_enroll(origin: str, alias: str, keyfile: Path, approval: object) -> tuple[str, str]:
        approval("https://kicad-mcp-pro.oaslananka.dev/devices/pair", "chal-1", "CODE-42")  # type: ignore
        return "dev-uuid-42", "fp-42"

    monkeypatch.setattr("kicad_mcp.cloud_pair.enroll", mock_enroll)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._read_owner_binding",
        lambda keyfile: {
            "origin": "https://kicad-mcp-pro.oaslananka.dev",
            "deviceId": "dev-uuid-42",
            "ownerSub": "sub-42",
        },
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.register_device_project",
        lambda origin, keyfile, alias: {"projectId": "proj-uuid-42", "alias": "My Project"},
    )

    def mock_enable_fail() -> None:
        raise RuntimeError("systemd unavailable")

    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._enable", mock_enable_fail)

    result = CliRunner().invoke(app, ["cloud", "setup", "--project-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "Browser opened for approval" in result.output
    assert "Background service start notice: systemd unavailable" in result.output
    expected_connector = "Enabled (Foreground ready)" if os.name == "posix" else "Off"
    assert f"Connector:       {expected_connector}" in result.output


def test_setup_owner_sub_missing_and_pairing_error(tmp_path: Path, monkeypatch) -> None:
    from kicad_mcp.cloud_pair import CloudPairingError

    (tmp_path / "board.kicad_pro").touch()
    keys_dir = tmp_path / "keys"
    projects_dir = tmp_path / "projects"
    keys_dir.mkdir(parents=True)
    projects_dir.mkdir(parents=True)

    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    monkeypatch.setattr("kicad_mcp.cloud_pair.default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.enroll",
        lambda origin, alias, keyfile, approval: ("dev-1", "fp-1"),
    )

    # 1. Missing ownerSub
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._read_owner_binding",
        lambda keyfile: {"origin": "https://kicad-mcp-pro.oaslananka.dev", "deviceId": "dev-1"},
    )
    res1 = CliRunner().invoke(
        app, ["cloud", "setup", "--no-browser", "--project-dir", str(tmp_path)]
    )
    assert res1.exit_code != 0
    assert "Owner identity missing from device binding" in res1.output

    # 2. CloudPairingError on register_device_project
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._read_owner_binding",
        lambda keyfile: {
            "origin": "https://kicad-mcp-pro.oaslananka.dev",
            "deviceId": "dev-1",
            "ownerSub": "sub-1",
        },
    )

    def mock_reg_fail(*args: object, **kwargs: object) -> tuple[str, str]:
        raise CloudPairingError("Signature rejected")

    monkeypatch.setattr("kicad_mcp.cloud_pair.register_device_project", mock_reg_fail)
    res2 = CliRunner().invoke(
        app, ["cloud", "setup", "--no-browser", "--project-dir", str(tmp_path)]
    )
    assert res2.exit_code != 0
    assert "Project registration failed on Cloud" in res2.output
