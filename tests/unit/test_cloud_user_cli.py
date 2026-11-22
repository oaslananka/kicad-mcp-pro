"""No real login, device enrollment, key or service change in CLI command tests."""

from __future__ import annotations

import webbrowser
from pathlib import Path

import pytest
from click import unstyle
from typer.testing import CliRunner

from kicad_mcp.server import app


@pytest.fixture(autouse=True)
def simulated_storage_support_for_mocked_cli_flows(monkeypatch) -> None:
    """These command tests mock enrollment; explicit negative tests cover native guards."""
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli._local_pairing_storage_supported",
        lambda: True,
    )
    # Existing POSIX tests explicitly test the old registry path; native NT
    # routes have their own real-Windows fixtures in test_cloud_windows_user_cli.
    monkeypatch.setattr("kicad_mcp.cloud_user_cli._is_windows", lambda: False)


def test_login_web_only_preserves_first_party_browser_without_cli_grant(monkeypatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open", lambda url, **_kwargs: seen.append(url) or True
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--web-only"])
    assert result.exit_code == 0, result.output
    assert seen == ["https://kicad-mcp-pro.oaslananka.dev/sign-in"]
    assert "Browser login does not grant device or project access." in result.output
    assert "cloud connect" in result.output


def test_login_headless_prints_link_but_never_launches_browser(monkeypatch) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_user_cli.webbrowser.open",
        lambda *_args, **_kw: pytest.fail("no browser expected"),
    )
    result = CliRunner().invoke(app, ["cloud", "login", "--no-browser", "--web-only"])
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


@pytest.mark.parametrize(
    ("options", "guidance"),
    [
        (["--enable-native-write"], "Windows"),
        (["--project-dir", "."], "cloud setup"),
    ],
)
def test_posix_connect_rejects_unsupported_options_before_pairing(
    monkeypatch, options, guidance
) -> None:
    seen = []
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: seen.append(args) or 0)
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: pytest.fail("Unsupported option must not inspect or change registry"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect", *options])
    assert seen == []
    assert result.exit_code == 2, result.output
    assert guidance in " ".join(unstyle(result.output).replace("│", " ").split())


def test_posix_connect_forwards_no_browser_to_pairing(monkeypatch, tmp_path) -> None:
    seen = []
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path)
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda args: seen.append(args) or 0)
    result = CliRunner().invoke(app, ["cloud", "connect", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert len(seen) == 1
    assert "--no-browser" in seen[0]


def test_cloud_pair_no_browser_prints_approval_link_without_launching(
    monkeypatch, tmp_path, capsys
) -> None:
    from kicad_mcp import cloud_pair

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setattr(cloud_pair, "default_registry_root", lambda: tmp_path)
    monkeypatch.setattr(cloud_pair, "_open_owner_private_dir", lambda _path: 999)
    monkeypatch.setattr("os.close", lambda _fd: None)
    monkeypatch.setattr(
        cloud_pair.webbrowser, "open", lambda *_a, **_kw: pytest.fail("browser must not open")
    )

    def enroll(_origin, _alias, _key, approval):
        approval("https://example.com/pair", "fixture-challenge", "FIXTURE-CODE")
        return "fixture-device", "fixture-fingerprint"

    monkeypatch.setattr(cloud_pair, "enroll", enroll)
    assert (
        cloud_pair.main(
            [
                "--cloud-origin",
                "https://example.com",
                "--alias",
                "fixture",
                "--begin-pairing",
                "--no-browser",
            ]
        )
        == 0
    )
    assert (
        "https://example.com/pair#challenge=fixture-challenge&code=FIXTURE-CODE"
        in capsys.readouterr().out
    )


@pytest.mark.parametrize("error_type", [OSError, webbrowser.Error])
def test_cloud_pair_browser_launch_error_prints_manual_approval_link(
    monkeypatch, capsys, error_type
) -> None:
    from kicad_mcp import cloud_pair

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    url = "https://example.com/pair#challenge=fixture-challenge&code=FIXTURE-CODE"
    calls = []

    def fail_open(review_url: str, **kwargs: object) -> bool:
        calls.append((review_url, kwargs))
        raise error_type("browser unavailable")

    monkeypatch.setattr(cloud_pair.webbrowser, "open", fail_open)
    cloud_pair._approval("https://example.com/pair", "fixture-challenge", "FIXTURE-CODE")
    assert calls == [(url, {"new": 2, "autoraise": True})]
    assert url in capsys.readouterr().out


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
    result = CliRunner().invoke(app, ["cloud", "login", "--web-only"])
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


@pytest.mark.parametrize("status", ["Connected", "Connecting", "Off"])
def test_setup_existing_valid_registration_reconnects(monkeypatch, tmp_path, status) -> None:
    (tmp_path / "board.kicad_pro").touch()
    monkeypatch.chdir(tmp_path)
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

    from kicad_mcp import cloud_user_cli

    states = iter([status, "Connecting"])
    starts: list[str] = []
    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._status", lambda: next(states))
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector._enable", lambda: starts.append("start") or 0
    )
    monkeypatch.setattr(cloud_user_cli.time, "sleep", lambda _seconds: None)

    result = CliRunner().invoke(app, ["cloud", "setup", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert "Found valid existing Cloud device and project registration" in result.output
    assert proj_id in result.output
    assert starts == (["start"] if status == "Off" else [])


@pytest.mark.parametrize(
    "failure",
    [
        "invalid-record",
        "different-origin",
        "missing-key",
        "start-failed",
        "still-off",
        "unavailable",
        "status-error",
    ],
)
def test_setup_existing_registration_needs_attention_without_repairing(
    monkeypatch, tmp_path, failure
) -> None:
    """Repeating setup must preserve existing identity and report failed recovery."""
    from kicad_mcp import cloud_user_cli

    project = tmp_path / "board.kicad_pro"
    project.touch()
    root = tmp_path / "cloud"
    projects = root / "projects"
    keys = root / "keys"
    projects.mkdir(parents=True)
    keys.mkdir()
    project_id = "33333333-3333-4333-8333-333333333333"
    slot = "44444444-4444-4444-8444-444444444444"
    record = projects / f"{project_id}.json"
    record.write_text("preserve-existing-record", encoding="utf-8")
    key = keys / f"{slot}.pem"
    if failure != "missing-key":
        key.write_text("preserve-existing-key", encoding="utf-8")
    baseline = {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()}

    def read_identity(_root):
        if failure == "invalid-record":
            raise ValueError("invalid private registry")
        return {
            "ownerSub": "github|test-owner",
            "cloudOrigin": (
                "https://other-cloud.example.com"
                if failure == "different-origin"
                else cloud_user_cli.DEFAULT_CLOUD_ORIGIN
            ),
            "deviceId": "55555555-5555-4555-8555-555555555555",
            "projectId": project_id,
            "keySlot": slot,
            "directory": str(tmp_path),
            "filenameStem": "board",
        }

    starts: list[str] = []

    def start():
        starts.append("start")
        if failure == "start-failed":
            raise RuntimeError("user service unavailable")
        return 0

    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: root)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity", read_identity
    )
    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._enable", start)

    def read_status():
        if failure == "status-error":
            raise OSError("user service manager unavailable")
        return "Unavailable" if failure == "unavailable" else "Off"

    monkeypatch.setattr("kicad_mcp.cloud_managed_connector._status", read_status)
    monkeypatch.setattr(cloud_user_cli.time, "sleep", lambda _seconds: None)
    enrollments: list[str] = []

    def unexpected_enrollment(*_args: object) -> None:
        enrollments.append("enroll")
        raise RuntimeError("unexpected enrollment")

    monkeypatch.setattr("kicad_mcp.cloud_pair.enroll", unexpected_enrollment)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--no-browser", "--project-dir", str(tmp_path)]
    )
    assert enrollments == []
    assert result.exit_code != 0, result.output
    assert "cloud status" in " ".join(unstyle(result.output).replace("│", " ").split())
    assert starts == (["start"] if failure in {"start-failed", "still-off"} else [])
    assert {p.name: p.read_bytes() for p in root.rglob("*") if p.is_file()} == baseline


def test_setup_handles_pairing_error(monkeypatch, tmp_path) -> None:
    from kicad_mcp.cloud_pair import CloudPairingError

    (tmp_path / "board.kicad_pro").touch()
    monkeypatch.chdir(tmp_path)
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


def test_setup_browser_approval_does_not_claim_service_ready_on_failure(
    tmp_path: Path, monkeypatch
) -> None:
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
    assert result.exit_code == 1
    assert "Browser opened for approval" in result.output
    assert "Cloud Connector could not start: RuntimeError" in result.output
    assert "Connector:       Unavailable" in result.output
    assert "Cloud device registered; Connector needs attention" in result.output


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


def test_cloud_setup_browse_uses_only_local_picker_without_cloud_upload(
    monkeypatch, tmp_path
) -> None:
    from kicad_mcp import cloud_user_cli

    folder = tmp_path / "pcb-project"
    folder.mkdir()
    (folder / "fixture.kicad_pro").write_text("{}", encoding="utf-8")
    calls: list[str] = []
    monkeypatch.setattr(
        cloud_user_cli,
        "_browse_local_project_folder",
        lambda: calls.append("picked") or folder,
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: tmp_path / "local-registry",
    )
    monkeypatch.setattr(
        cloud_user_cli,
        "_try_reconnect_existing",
        lambda _root, _origin: calls.append("reconnect") or True,
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--browse", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == ["picked", "reconnect"]
    assert not (tmp_path / "local-registry").exists()


def test_cloud_setup_rejects_conflicting_picker_and_directory(monkeypatch, tmp_path) -> None:
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(
        cloud_user_cli,
        "_browse_local_project_folder",
        lambda: pytest.fail("conflicting options must never open picker"),
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--browse", "--project-dir", str(tmp_path)])
    # Typer/Rich wraps and colorizes error messages differently on each OS.
    # The validation exit code, plus the failing picker mock, is the contract.
    assert result.exit_code == 2
    assert "Usage:" in result.output


def test_cloud_setup_cancelled_picker_cannot_enroll_or_change_registry(
    monkeypatch, tmp_path
) -> None:
    from kicad_mcp import cloud_user_cli

    def cancelled() -> Path:
        raise cloud_user_cli.typer.BadParameter(
            "No project folder selected. Setup was not changed."
        )

    monkeypatch.setattr(cloud_user_cli, "_browse_local_project_folder", cancelled)
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: pytest.fail("canceled choice must stop before registry access"),
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--browse"])
    assert result.exit_code != 0
    assert "No project folder selected" in result.output


@pytest.mark.parametrize(
    ("status", "path_text", "expected"),
    [
        (0, "/home/example/Circuit Board\n", "/home/example/Circuit Board"),
        (1, "", None),
        (0, "  \n", None),
    ],
)
def test_cloud_native_zenity_folder_picker(
    monkeypatch, status: int, path_text: str, expected: str | None
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    argv_seen: list[list[str]] = []
    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(cloud_user_cli.shutil, "which", lambda _name: "/usr/bin/zenity")

    def dialog_command(argv, **kwargs: object):
        argv_seen.append(argv)
        assert argv[0] == "/usr/bin/zenity"
        assert "--directory" in argv
        assert kwargs == {
            "capture_output": True,
            "text": True,
            "check": False,
            "timeout": 120,
        }
        return SimpleNamespace(returncode=status, stdout=path_text)

    monkeypatch.setattr(cloud_user_cli.subprocess, "run", dialog_command)
    if expected is None:
        with pytest.raises(cloud_user_cli.typer.BadParameter, match="No project folder"):
            cloud_user_cli._browse_local_project_folder()
    else:
        assert cloud_user_cli._browse_local_project_folder() == Path(expected)
    assert len(argv_seen) == 1


@pytest.mark.parametrize("reason", ["timeout", "unavailable"])
def test_cloud_native_zenity_picker_launch_failure(monkeypatch, reason: str) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(cloud_user_cli.shutil, "which", lambda _name: "/usr/bin/zenity")

    def error_command(_argv, **_kwargs: object):
        if reason == "timeout":
            raise cloud_user_cli.subprocess.TimeoutExpired("/usr/bin/zenity", 120)
        raise OSError("display backend unavailable")

    monkeypatch.setattr(cloud_user_cli.subprocess, "run", error_command)
    with pytest.raises(cloud_user_cli.typer.BadParameter, match="Folder picker unavailable"):
        cloud_user_cli._browse_local_project_folder()


@pytest.mark.parametrize(
    ("selected", "should_succeed"),
    [("/home/example/PCB fixture", True), ("", False)],
)
def test_cloud_native_tkinter_folder_picker(
    monkeypatch, selected: str, should_succeed: bool
) -> None:
    import sys as interpreter
    from types import ModuleType, SimpleNamespace

    from kicad_mcp import cloud_user_cli

    events: list[str] = []
    dialog = SimpleNamespace(
        withdraw=lambda: events.append("hide"),
        destroy=lambda: events.append("destroy"),
    )
    fake_tk = ModuleType("tkinter")
    fake_tk.Tk = lambda: dialog  # type: ignore[attr-defined]

    def select_directory(**options: object):
        assert options["parent"] is dialog
        assert options["mustexist"] is True
        events.append("select")
        return selected

    fake_tk.filedialog = SimpleNamespace(askdirectory=select_directory)  # type: ignore[attr-defined]
    monkeypatch.setitem(interpreter.modules, "tkinter", fake_tk)
    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="darwin"))
    if should_succeed:
        assert cloud_user_cli._browse_local_project_folder() == Path(selected)
    else:
        with pytest.raises(cloud_user_cli.typer.BadParameter, match="No project folder"):
            cloud_user_cli._browse_local_project_folder()
    assert events == ["hide", "select", "destroy"]


@pytest.mark.parametrize(
    "case", ["selected", "cancelled", "non_filesystem", "com_unavailable", "dll_unavailable"]
)
def test_windows_native_folder_picker_uses_trusted_system_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: str
) -> None:
    import ctypes
    from types import SimpleNamespace
    from unittest.mock import Mock

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="win32"))
    events: list[str] = []

    def write_folder(_pidl: int, output: object, _size: int, _flags: int) -> int:
        events.append("get_path")
        if case == "non_filesystem":
            return 0
        output.value = str(tmp_path)  # type: ignore[attr-defined]
        return 1

    shell = SimpleNamespace(
        SHBrowseForFolderW=Mock(return_value=None if case == "cancelled" else 123),
        SHGetPathFromIDListEx=Mock(side_effect=write_folder),
    )
    ole = SimpleNamespace(
        CoInitializeEx=Mock(return_value=-1 if case == "com_unavailable" else 0),
        CoUninitialize=Mock(),
        CoTaskMemFree=Mock(),
    )
    trusted = {"shell32.dll": shell, "ole32.dll": ole}

    def load_dll(name: str, *, winmode: int) -> SimpleNamespace:
        assert name in trusted
        assert winmode == 0x800  # LOAD_LIBRARY_SEARCH_SYSTEM32
        events.append("dll:" + name)
        if case == "dll_unavailable":
            raise OSError("System directory unavailable")
        return trusted[name]

    monkeypatch.setattr(ctypes, "WinDLL", load_dll, raising=False)
    if case == "selected":
        assert cloud_user_cli._browse_local_project_folder() == tmp_path
    else:
        message = (
            "No project folder selected"
            if case == "cancelled"
            else "Windows folder picker unavailable"
        )
        with pytest.raises(cloud_user_cli.typer.BadParameter, match=message):
            cloud_user_cli._browse_local_project_folder()

    if case == "dll_unavailable":
        assert events == ["dll:shell32.dll"]
        return
    if case == "com_unavailable":
        ole.CoUninitialize.assert_not_called()
        shell.SHBrowseForFolderW.assert_not_called()
        return

    ole.CoUninitialize.assert_called_once()
    shell.SHBrowseForFolderW.assert_called_once()
    assert shell.SHBrowseForFolderW.call_args.args[0]._obj.hwndOwner is None
    if case == "cancelled":
        shell.SHGetPathFromIDListEx.assert_not_called()
        ole.CoTaskMemFree.assert_not_called()
    else:
        assert events[-1] == "get_path"
        shell.SHGetPathFromIDListEx.assert_called_once()
        ole.CoTaskMemFree.assert_called_once_with(123)


@pytest.mark.parametrize("reason", ["not_installed", "display_error", "dialog_error"])
def test_cloud_native_tkinter_picker_errors_cleanly(monkeypatch, reason: str) -> None:
    import sys as interpreter
    from types import ModuleType, SimpleNamespace

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="darwin"))
    if reason == "not_installed":
        monkeypatch.setitem(interpreter.modules, "tkinter", None)
    else:
        events: list[str] = []
        dialog = SimpleNamespace(
            withdraw=lambda: events.append("hide"),
            destroy=lambda: events.append("destroy"),
        )
        fake_tk = ModuleType("tkinter")
        if reason == "display_error":

            def raise_display():
                raise RuntimeError("no desktop session")

            fake_tk.Tk = raise_display  # type: ignore[attr-defined]
        else:
            fake_tk.Tk = lambda: dialog  # type: ignore[attr-defined]

            def raise_dialog(**_kwargs: object):
                raise OSError("folder dialog cannot launch")

            fake_tk.filedialog = SimpleNamespace(askdirectory=raise_dialog)  # type: ignore[attr-defined]
        monkeypatch.setitem(interpreter.modules, "tkinter", fake_tk)
    with pytest.raises(cloud_user_cli.typer.BadParameter, match="No graphical folder picker"):
        cloud_user_cli._browse_local_project_folder()
    if reason == "dialog_error":
        assert events == ["hide", "destroy"]


def test_cloud_setup_blocks_unsupported_owner_key_storage_before_pairing(
    monkeypatch, tmp_path: Path
) -> None:
    """No Cloud request or registry write may precede the native storage guard."""
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").touch()
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "_local_pairing_storage_supported", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.enroll",
        lambda *_args, **_kwargs: pytest.fail("Unsupported platform cannot enroll"),
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: pytest.fail("Unsupported platform cannot create registry"),
    )
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--project-dir", str(project), "--no-browser"]
    )
    assert result.exit_code != 0
    assert "owner-private key storage" in result.output
    assert "No device or project was registered" in result.output


def test_cloud_connect_blocks_unsupported_storage_before_cloud_pairing(
    monkeypatch,
) -> None:
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "_local_pairing_storage_supported", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.main",
        lambda *_args: pytest.fail("No remote pairing on unsupported platform"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "owner-private key storage" in result.output


def test_cloud_setup_rejects_empty_explicit_folder_without_registration(
    monkeypatch, tmp_path: Path
) -> None:
    project = tmp_path / "empty"
    project.mkdir()
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: pytest.fail("Empty directory must not register"),
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--project-dir", str(project)])
    assert result.exit_code != 0
    assert "No KiCad project found" in result.output


def test_cloud_setup_headless_nonproject_cwd_fails_without_opening_picker(
    monkeypatch, tmp_path: Path
) -> None:
    from kicad_mcp import cloud_user_cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr(
        cloud_user_cli,
        "_browse_local_project_folder",
        lambda: pytest.fail("Headless must never open a blocking dialog"),
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--no-browser"])
    assert result.exit_code != 0
    assert "No KiCad project found in the current directory" in result.output


def test_cloud_setup_interactive_nonproject_cwd_uses_native_picker(
    monkeypatch, tmp_path: Path
) -> None:
    from kicad_mcp import cloud_user_cli

    current = tmp_path / "working"
    current.mkdir()
    selected = tmp_path / "valid-board"
    selected.mkdir()
    (selected / "chosen.kicad_pro").touch()
    monkeypatch.chdir(current)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    calls: list[str] = []
    monkeypatch.setattr(
        cloud_user_cli,
        "_browse_local_project_folder",
        lambda: calls.append("browse") or selected,
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path / "cloud"
    )
    monkeypatch.setattr(
        cloud_user_cli,
        "_try_reconnect_existing",
        lambda _root, _origin: calls.append("reconnect") or True,
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--no-browser"])
    assert result.exit_code == 0, result.output
    assert calls == ["browse", "reconnect"]
    assert not (tmp_path / "cloud").exists()


def test_cloud_login_connects_cli_in_one_browser_approval(monkeypatch) -> None:
    seen: list[tuple[str, bool]] = []

    def approve(origin: str, *, no_browser: bool = False) -> None:
        seen.append((origin, no_browser))

    monkeypatch.setattr("kicad_mcp.cloud_owner_management.authorize", approve)
    direct = CliRunner().invoke(app, ["cloud", "login"])
    assert direct.exit_code == 0, direct.output
    assert seen == [("https://kicad-mcp-pro.oaslananka.dev", False)]
    assert "cloud setup" in direct.output
    headless = CliRunner().invoke(app, ["cloud", "login", "--no-browser"])
    assert headless.exit_code == 0, headless.output
    assert seen[-1] == ("https://kicad-mcp-pro.oaslananka.dev", True)


def test_windows_cloud_connect_starts_existing_foreground_remote_without_a_background_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_user_cli as cli

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "remote", lambda **options: calls.append(options))
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["browse"] is False
    assert calls[0]["repair_device"] is False
    assert calls[0]["alias"] is None

    custom = CliRunner().invoke(app, ["cloud", "connect", "--alias", "Lab PC"])
    assert custom.exit_code == 0, custom.output
    assert calls[-1]["alias"] == "Lab PC"


def test_windows_connect_new_device_uses_foreground_pairing_and_never_schedules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import cloud_windows_user_cli as windows

    paired: list[dict[str, object]] = []
    remote: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(windows, "setup_windows", lambda **options: paired.append(options))
    monkeypatch.setattr(cli, "remote", lambda **options: remote.append(options))
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device", "--alias", "Bench PC"])
    assert result.exit_code == 0, result.output
    assert len(paired) == 1
    assert len(remote) == 1
    assert paired[0]["new_device"] is True
    assert paired[0]["start_background"] is False
    assert paired[0]["browse"] is True
    assert paired[0]["alias"] == "Bench PC"
    assert remote[0]["alias"] == "Bench PC"
    assert remote[0]["repair_device"] is False


def test_windows_cloud_connect_explicit_write_flag_forwards_to_foreground(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_user_cli as cli

    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "remote", lambda **options: calls.append(options))
    result = CliRunner().invoke(app, ["cloud", "connect", "--enable-native-write"])
    assert result.exit_code == 0, result.output
    assert calls[-1]["allow_native_write"] is True


def test_windows_cloud_write_issuer_requires_owner_terminal_before_vault_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import cloud_windows_write_issuer as issuer

    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr(
        issuer,
        "trust_owner_windows_write_issuer",
        lambda *_args, **_kwargs: pytest.fail("Headless trust prohibited"),
    )
    public_key = tmp_path / "issuer.pem"
    public_key.write_bytes(b"test")
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "trust-write-issuer",
            "--public-key-file",
            str(public_key),
            "--sha256",
            "a" * 64,
        ],
    )
    assert result.exit_code != 0


def test_windows_owner_can_trust_explicit_independently_verified_public_issuer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import cloud_windows_connector, cloud_windows_write_issuer

    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=cli.DEFAULT_CLOUD_ORIGIN, record_id="a" * 32),
    )
    seen: list[tuple[str, bytes, str]] = []
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "trust_owner_windows_write_issuer",
        lambda record, key, *, expected_spki_sha256: seen.append(
            (record, key, expected_spki_sha256)
        ),
    )
    from kicad_mcp import cloud_windows_write_marker

    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: tmp_path,
    )
    pem = tmp_path / "trusted-issuer.pem"
    pem.write_bytes(b"x" * 120)
    sha256 = "a" * 64
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "trust-write-issuer",
            "--public-key-file",
            str(pem),
            "--sha256",
            sha256,
        ],
    )
    assert result.exit_code == 0, result.output
    assert seen == [("a" * 32, b"x" * 120, sha256)]
    assert "Cloud also requires explicit OAuth" in result.output


def test_windows_connect_cannot_pair_new_device_and_enable_writes_in_one_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import cloud_windows_user_cli

    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "setup_windows",
        lambda **_: pytest.fail("Pairing must not begin on write opt-in"),
    )
    result = CliRunner().invoke(app, ["cloud", "connect", "--new-device", "--enable-native-write"])
    assert result.exit_code != 0
    assert "read-only access first" in result.output


@pytest.mark.parametrize("case", ["unpaired", "wrong_origin", "missing_file", "oversize", "denied"])
def test_write_issuer_cli_negative_paths_leave_owner_vault_and_project_untouched(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    case: str,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import cloud_windows_connector, cloud_windows_write_issuer
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: (
            None
            if case == "unpaired"
            else SimpleNamespace(
                origin="https://wrong.example"
                if case == "wrong_origin"
                else cli.DEFAULT_CLOUD_ORIGIN,
                record_id="a" * 32,
            )
        ),
    )
    writes: list[str] = []

    def trust(*_args: object, **_kwargs: object) -> None:
        writes.append("attempt")
        if case == "denied":
            raise LocalWriteDeniedError("request denied")

    monkeypatch.setattr(cloud_windows_write_issuer, "trust_owner_windows_write_issuer", trust)
    from kicad_mcp import cloud_windows_write_marker

    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: tmp_path,
    )
    pem = tmp_path / "issuer.pem"
    if case != "missing_file":
        pem.write_bytes(b"A" * (513 if case == "oversize" else 120))
    result = CliRunner().invoke(
        app, ["cloud", "trust-write-issuer", "--public-key-file", str(pem), "--sha256", "a" * 64]
    )
    assert result.exit_code != 0
    assert writes == (["attempt"] if case == "denied" else [])


def test_owner_trust_bootstraps_write_marker_without_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli as cli
    from kicad_mcp import (
        cloud_windows_connector,
        cloud_windows_write_issuer,
        cloud_windows_write_marker,
    )

    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        cloud_windows_connector,
        "selected_project",
        lambda: SimpleNamespace(origin=cli.DEFAULT_CLOUD_ORIGIN, record_id="a" * 32),
    )
    events: list[str] = []
    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: events.append("marker") or tmp_path,
    )
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "trust_owner_windows_write_issuer",
        lambda *args, **kwargs: events.append("pin"),
    )
    keyfile = tmp_path / "test.pem"
    keyfile.write_bytes(b"x" * 120)
    result = CliRunner().invoke(
        app,
        ["cloud", "trust-write-issuer", "--public-key-file", str(keyfile), "--sha256", "a" * 64],
    )
    assert result.exit_code == 0, result.output
    assert events == ["marker", "pin"]


def test_windows_bare_cloud_preserves_readonly_default_without_trusting_write_issuer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Starting the ordinary Cloud journey must not request native edit authority."""
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli as cli

    project = SimpleNamespace(record_id="existing-owner-record")
    launches: list[dict[str, object]] = []
    write_issuer_trust: list[object] = []
    monkeypatch.setattr(cli, "_is_windows", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_windows_connector.selected_project", lambda: project)
    monkeypatch.setattr(
        cli,
        "_connect_windows_foreground",
        lambda *_args, **kwargs: launches.append(kwargs),
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_write_issuer.trust_bundled_owner_cloud_issuer",
        lambda *args, **kwargs: write_issuer_trust.append((args, kwargs)),
    )

    result = CliRunner().invoke(app, ["cloud"])
    assert result.exit_code == 0, result.output
    assert len(launches) == 1
    assert launches[0]["allow_native_write"] is False
    assert write_issuer_trust == []


@pytest.mark.parametrize("exit_code", [0, 1])
def test_posix_registered_connect_uses_interactive_foreground(
    monkeypatch, tmp_path: Path, exit_code: int
) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("private fixture")
    record = {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev", "deviceId": "fixture"}
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity", lambda _: record
    )
    monkeypatch.setattr("kicad_mcp.cloud_user_cli._owner_terminal", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda *_: pytest.fail("no new pairing"))
    calls = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.run_foreground",
        lambda expected: calls.append(expected) or exit_code,
        raising=False,
    )
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code == exit_code, result.output
    assert calls == [record]
    assert "terminal open" in result.output
    assert "read-only" in result.output


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_interactive_setup_uses_foreground_without_background_service(
    monkeypatch, tmp_path: Path, platform: str
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").touch()
    registry = tmp_path / "registry"
    origin = "https://kicad-mcp-pro.oaslananka.dev"
    device = "11111111-1111-4111-8111-111111111111"
    project_id = "22222222-2222-4222-8222-222222222222"
    calls = []
    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr("kicad_mcp.cloud_pair.enroll", lambda *_: (device, "0" * 64))
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair_keys._read_owner_binding", lambda _: {"ownerSub": "github|test-owner"}
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.register_device_project", lambda *_a, **_k: {"projectId": project_id}
    )
    monkeypatch.setattr(
        cloud_user_cli, "_start_connector", lambda: pytest.fail("must not start background service")
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.run_foreground", lambda record: calls.append(record) or 0
    )
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--project-dir", str(project), "--no-browser"]
    )
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["deviceId"] == device
    assert calls[0]["cloudOrigin"] == origin
    assert calls[0]["directory"] == str(project.resolve())
    assert (registry / "projects" / f"{project_id}.json").is_file()
    assert "terminal open" in result.output
    assert "Setup Complete!" not in result.output


def test_darwin_headless_setup_rejects_before_registration(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr("kicad_mcp.cloud_pair.enroll", lambda *_: pytest.fail("no enrollment"))
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: pytest.fail("no registry")
    )
    (tmp_path / "board.kicad_pro").touch()
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--project-dir", str(tmp_path), "--no-browser"]
    )
    assert result.exit_code != 0
    assert "interactive" in result.output
    assert "No device or project was registered" in result.output


@pytest.mark.parametrize("args", [["cloud"], ["cloud", "connect"]])
def test_posix_first_interactive_command_routes_to_setup(monkeypatch, tmp_path: Path, args) -> None:
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root", lambda: tmp_path / "registry"
    )
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda *_: pytest.fail("pairing-only path"))
    calls = []
    monkeypatch.setattr(cloud_user_cli, "setup", lambda **kwargs: calls.append(kwargs))
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert calls[0]["new_device"] is False
    assert calls[0]["project_dir"] is None
    assert not (tmp_path / "registry").exists()


def test_posix_bare_cloud_requires_owner_terminal(monkeypatch) -> None:
    from kicad_mcp import cloud_user_cli

    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr(
        "kicad_mcp.cloud_local_registry.default_registry_root",
        lambda: pytest.fail("no registry access"),
    )
    result = CliRunner().invoke(app, ["cloud"])
    assert result.exit_code != 0
    assert "interactive" in result.output


def test_posix_interactive_connect_preserves_unbound_keys(monkeypatch, tmp_path: Path) -> None:
    from kicad_mcp import cloud_user_cli

    registry = tmp_path / "registry"
    keys = registry / "keys"
    keys.mkdir(parents=True)
    key = keys / "existing.pem"
    key.write_bytes(b"fixture key")
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(cloud_user_cli, "setup", lambda **_: pytest.fail("no duplicate enrollment"))
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda *_: pytest.fail("no duplicate pairing"))
    result = CliRunner().invoke(app, ["cloud", "connect"])
    assert result.exit_code != 0
    assert "existing" in result.output.lower()
    assert key.read_bytes() == b"fixture key"


def test_posix_bare_cloud_reuses_registered_device(monkeypatch, tmp_path: Path) -> None:
    registry = tmp_path / "cloud"
    (registry / "projects").mkdir(parents=True)
    (registry / "projects" / "fixture.json").write_text("fixture")
    record = {"cloudOrigin": "https://kicad-mcp-pro.oaslananka.dev", "deviceId": "fixture"}
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_registered_pilot._single_registered_identity", lambda _: record
    )
    monkeypatch.setattr("kicad_mcp.cloud_user_cli._owner_terminal", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_pair.main", lambda *_: pytest.fail("no duplicate pairing"))
    monkeypatch.setattr("kicad_mcp.cloud_user_cli.setup", lambda **_: pytest.fail("no new setup"))
    calls = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_managed_connector.run_foreground",
        lambda expected: calls.append(expected) or 0,
    )
    result = CliRunner().invoke(app, ["cloud"])
    assert result.exit_code == 0, result.output
    assert calls == [record]


def test_posix_setup_preserves_unbound_keys_without_explicit_new_device(
    monkeypatch, tmp_path: Path
) -> None:
    from kicad_mcp import cloud_user_cli

    registry = tmp_path / "registry"
    keys = registry / "keys"
    keys.mkdir(parents=True)
    key = keys / "existing.pem"
    key.write_bytes(b"fixture key")
    project = tmp_path / "board"
    project.mkdir()
    (project / "board.kicad_pro").touch()
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr("kicad_mcp.cloud_local_registry.default_registry_root", lambda: registry)
    monkeypatch.setattr(
        "kicad_mcp.cloud_pair.enroll", lambda *_: pytest.fail("no duplicate enrollment")
    )
    result = CliRunner().invoke(app, ["cloud", "setup", "--project-dir", str(project)])
    assert result.exit_code != 0
    assert "Existing device keys" in result.output
    assert key.read_bytes() == b"fixture key"
    assert list(keys.iterdir()) == [key]
