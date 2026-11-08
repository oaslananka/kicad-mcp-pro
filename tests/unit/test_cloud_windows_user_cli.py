"""Windows terminal onboarding contract: no real browser, Cloud or scheduled task."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kicad_mcp import cloud_user_cli, cloud_windows_user_cli
from kicad_mcp.cloud_windows_enrollment import (
    WindowsEnrolledDevice,
    WindowsRegisteredProject,
)
from kicad_mcp.cloud_windows_local_selection import WindowsLocalProjectSelection
from kicad_mcp.server import app

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Native Windows owner session only")

ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"


@pytest.fixture
def windows_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[Path, list[str], WindowsRegisteredProject, WindowsLocalProjectSelection]:
    folder = tmp_path / "demo"
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    events: list[str] = []
    device = WindowsEnrolledDevice(
        record_id="b" * 32,
        origin=ORIGIN,
        owner_sub="owner",
        device_id="19ee4be9-0aec-448e-9873-721ae113ec02",
        fingerprint="f" * 64,
    )
    project = WindowsRegisteredProject(
        registration_id="a" * 32,
        record_id=device.record_id,
        origin=device.origin,
        owner_sub=device.owner_sub,
        device_id=device.device_id,
        fingerprint=device.fingerprint,
        project_id="29ee4be9-0aec-448e-9873-721ae113ec02",
        filename_stem="demo",
    )
    selected = WindowsLocalProjectSelection(
        registration_id=project.registration_id,
        record_id=project.record_id,
        device_id=project.device_id,
        project_id=project.project_id,
        filename_stem=project.filename_stem,
        directory=folder,
    )
    state = {"selected": None, "connector": "Off"}

    monkeypatch.setattr(cloud_user_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        cloud_user_cli,
        "_perform_approval",
        lambda _page, _challenge, _code, _no_browser: events.append("browser_approval"),
    )
    monkeypatch.setattr(
        cloud_windows_user_cli.typer,
        "confirm",
        lambda *_args, **_kwargs: events.append("owner_confirm") or True,
    )

    def enroll(**kwargs: object) -> WindowsEnrolledDevice:
        events.append("enroll")
        assert kwargs["origin"] == ORIGIN
        assert kwargs["alias"] == "Lab PC"
        kwargs["owner_approval"](ORIGIN + "/devices/pairing", "challenge", "CODE-22")
        return device

    def register(the_device: WindowsEnrolledDevice, **kwargs: object) -> WindowsRegisteredProject:
        events.append("register")
        assert the_device == device
        assert kwargs["filename_stem"] == "demo"
        return project

    def bind(
        the_project: WindowsRegisteredProject,
        path: Path,
        *,
        owner_confirm,
    ) -> WindowsLocalProjectSelection:
        events.append("bind")
        assert the_project == project and path == folder
        assert owner_confirm(path)
        return selected

    def remember(the_project: WindowsRegisteredProject) -> None:
        events.append("remember")
        assert the_project == project
        state["selected"] = the_project

    def activate(the_project: WindowsRegisteredProject, *, owner_confirm) -> None:
        events.append("schedule")
        assert the_project == project
        assert owner_confirm(the_project)
        state["connector"] = "Scheduled (connection unverified)"

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", enroll)
    monkeypatch.setattr(cloud_windows_user_cli, "register_windows_project", register)
    monkeypatch.setattr(cloud_windows_user_cli, "bind_owner_selected_project", bind)
    monkeypatch.setattr(cloud_windows_user_cli, "remember_selected_project", remember)
    monkeypatch.setattr(cloud_windows_user_cli, "selected_project", lambda: state["selected"])
    monkeypatch.setattr(
        cloud_windows_user_cli, "inspect_owner_selected_project", lambda _project: selected
    )
    monkeypatch.setattr(cloud_windows_user_cli, "scheduler_state", lambda: state["connector"])
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "local_state",
        lambda: "Off" if state["connector"] == "Off" else "Configured (not connected)",
    )
    monkeypatch.setattr(cloud_windows_user_cli, "enable_windows_connector", activate)
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "disable_windows_connector",
        lambda: events.append("disable") or state.update(connector="Off") or True,
    )
    return folder, events, project, selected


def test_windows_cli_first_setup_is_owner_approved_and_does_not_claim_connected(
    windows_cli,
) -> None:
    folder, events, _project, _selected = windows_cli
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder), "--no-browser"]
    )
    assert result.exit_code == 0, result.output
    assert events == [
        "owner_confirm",
        "enroll",
        "browser_approval",
        "register",
        "bind",
        "remember",
        "schedule",
    ]
    assert "Connector scheduled (connection unverified)" in result.output
    assert "Cloud owner must separately approve access" in result.output
    assert "Connected!" not in result.output


def test_windows_second_setup_reuses_selected_identity_without_new_enrollment(
    windows_cli,
) -> None:
    folder, events, _project, _selected = windows_cli
    first = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert first.exit_code == 0, first.output
    events.clear()
    second = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert second.exit_code == 0, second.output
    assert not events
    assert "Existing Windows Cloud device:" in second.output
    assert "No new device registration" in second.output


def test_windows_headless_setup_refuses_before_cloud(
    windows_cli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder, events, _project, _selected = windows_cli
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert result.exit_code != 0
    assert not events


def test_windows_cancel_refuses_before_cloud(
    windows_cli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder, events, _project, _selected = windows_cli
    monkeypatch.setattr(cloud_windows_user_cli.typer, "confirm", lambda *_a, **_kw: False)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert result.exit_code != 0
    assert "Owner cancelled" in result.output
    assert not events


def test_expired_owner_browser_approval_has_actionable_retry_message(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli

    def expire(**_kwargs: object) -> None:
        raise cloud_windows_user_cli.WindowsEnrollmentTimeoutError(
            "Device approval expired; no device was redeemed. "
            "Start cloud setup again and approve within five minutes."
        )

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", expire)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert result.exit_code != 0
    assert "approval expired" in result.output
    assert "five minutes" in result.output
    assert "Windows Cloud registration was not fully completed" not in result.output
    assert events == ["owner_confirm"]


def test_owner_denial_returns_specific_cli_message_and_creates_no_device(
    windows_cli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder, events, _project, _selected = windows_cli

    def deny(**_kwargs: object) -> None:
        raise cloud_windows_user_cli.WindowsEnrollmentDeniedError(
            "Device pairing was denied in the browser. No device was registered."
        )

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", deny)
    result = CliRunner().invoke(
        app,
        ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)],
        terminal_width=200,
    )
    assert result.exit_code != 0
    assert "denied" in result.output
    assert "registered" in result.output
    assert "Windows Cloud registration was not fully completed" not in result.output
    assert events == ["owner_confirm"]


def test_windows_empty_project_refuses_before_cloud(
    windows_cli,
    tmp_path: Path,
) -> None:
    _folder, events, _project, _selected = windows_cli
    empty = tmp_path / "empty"
    empty.mkdir()
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(empty)]
    )
    assert result.exit_code != 0
    assert not events


def test_windows_connector_failure_does_not_claim_success(
    windows_cli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder, events, _project, _selected = windows_cli

    def fail_schedule(*_args: object, **_kwargs: object) -> None:
        events.append("schedule_failed")
        raise RuntimeError("scheduled task cannot launch")

    monkeypatch.setattr(cloud_windows_user_cli, "enable_windows_connector", fail_schedule)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert result.exit_code != 0
    assert events[-1] == "schedule_failed"
    assert "Connector did not start" in result.output
    assert "Connected" not in result.output


def test_windows_status_displays_selected_project_and_opaque_connector_state(
    windows_cli,
) -> None:
    folder, _events, _project, _selected = windows_cli
    first = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert first.exit_code == 0, first.output
    status = CliRunner().invoke(app, ["cloud", "status"])
    assert status.exit_code == 0, status.output
    assert "connection unverified" in status.output
    assert "Cloud owner grants" in status.output
    assert str(folder) in status.output


def test_windows_status_before_registration_does_not_trigger_cloud(
    windows_cli,
) -> None:
    _folder, events, _project, _selected = windows_cli
    status = CliRunner().invoke(app, ["cloud", "status"])
    assert status.exit_code == 0, status.output
    assert "No owner-selected" in status.output
    assert not events


def test_windows_disable_and_disconnect_are_local_only(
    windows_cli,
) -> None:
    _folder, events, _project, _selected = windows_cli
    for command in ("disable", "disconnect"):
        result = CliRunner().invoke(app, ["cloud", command])
        assert result.exit_code == 0, result.output
        assert "Cloud device/project grants must be revoked separately" in result.output
    assert events == ["disable", "disable"]


def test_windows_reconnect_requires_existing_user_selection(
    windows_cli,
) -> None:
    _folder, events, _project, _selected = windows_cli
    result = CliRunner().invoke(app, ["cloud", "reconnect"])
    assert result.exit_code != 0
    assert "No registered Windows project" in result.output
    assert not events


def test_windows_cloud_connect_uses_same_onboarding_contract(
    windows_cli,
) -> None:
    folder, events, _project, _selected = windows_cli
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "connect",
            "--alias",
            "Lab PC",
            "--project-dir",
            str(folder),
            "--no-browser",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "browser_approval" in events
    assert "register" in events
    assert "Connector scheduled (connection unverified)" in result.output


def test_native_posix_guards_still_exist(
    windows_cli,
) -> None:
    assert callable(cloud_user_cli._local_pairing_storage_supported)


def test_windows_cwd_and_owner_chosen_folder_are_verified(
    windows_cli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder, _events, _project, _selected = windows_cli
    monkeypatch.chdir(folder)
    path, stem = cloud_windows_user_cli._choose_project(
        None, browse=False, picker=lambda: pytest.fail("unexpected picker")
    )
    assert (path, stem) == (folder, "demo")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cloud_windows_user_cli.typer, "prompt", lambda *_args: str(folder))
    assert cloud_windows_user_cli._choose_project(None, browse=False, picker=lambda: folder) == (
        folder,
        "demo",
    )
    assert cloud_windows_user_cli._choose_project(
        None, browse=True, picker=lambda: folder.relative_to(tmp_path)
    ) == (folder, "demo")


def test_windows_project_selector_limits_directory_and_rejects_invalid_picker(
    windows_cli, tmp_path: Path
) -> None:
    _folder, events, _project, _selected = windows_cli
    with pytest.raises(Exception, match="Invalid local KiCad project directory"):
        cloud_windows_user_cli._choose_project(
            None,
            browse=True,
            picker=lambda: "not-a-path",  # type: ignore[return-value]
        )

    crowded = tmp_path / "crowded"
    crowded.mkdir()
    (crowded / "demo.kicad_pro").touch()
    for i in range(129):
        (crowded / f"unrelated-{i}.txt").touch()
    with pytest.raises(Exception, match="unsafe link") as caught:
        cloud_windows_user_cli._choose_project(
            crowded, browse=False, picker=lambda: pytest.fail("unexpected picker")
        )
    assert "too many entries" in str(caught.value.__cause__)
    assert not events


def test_windows_existing_device_cannot_be_replaced_or_switch_origin(
    windows_cli,
) -> None:
    folder, events, _project, _selected = windows_cli
    first = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert first.exit_code == 0
    events.clear()
    again = CliRunner().invoke(
        app,
        ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder), "--new-device"],
    )
    assert again.exit_code != 0
    assert "already registered" in again.output
    assert not events

    with pytest.raises(Exception, match="different Cloud origin"):
        cloud_windows_user_cli.setup_windows(
            origin=ORIGIN + "/another",
            alias="Lab PC",
            project_dir=folder,
            browse=False,
            new_device=False,
            approval=lambda *_: pytest.fail("owner approval not reached"),
            picker=lambda: folder,
            owner_terminal=lambda: True,
        )
    assert not events


def test_windows_existing_device_off_may_remain_off_by_owner_choice(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli
    assert (
        CliRunner()
        .invoke(app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)])
        .exit_code
        == 0
    )
    events.clear()
    monkeypatch.setattr(cloud_windows_user_cli, "local_state", lambda: "Off")
    monkeypatch.setattr(cloud_windows_user_cli.typer, "confirm", lambda *_a, **_kw: False)
    result = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert result.exit_code == 0
    assert "remains Off" in result.output
    assert not events


def test_windows_corrupt_selection_and_registration_errors_never_start_connector(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "selected_project",
        lambda: (_ for _ in ()).throw(OSError("vault read failed")),
    )
    error = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert error.exit_code != 0
    assert "needs local repair" in error.output
    assert not events

    monkeypatch.setattr(cloud_windows_user_cli, "selected_project", lambda: None)
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "register_windows_project",
        lambda *_a, **_kw: (_ for _ in ()).throw(OSError("cloud registration failure")),
    )
    bad_register = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert bad_register.exit_code != 0
    assert "not fully completed" in bad_register.output
    assert "schedule" not in events


def test_windows_enable_requires_owner_consent_and_preserves_current_session(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli
    with pytest.raises(Exception, match="interactive owner terminal"):
        cloud_windows_user_cli.enable_existing(owner_terminal=lambda: False)
    missing = CliRunner().invoke(app, ["cloud", "enable"])
    assert missing.exit_code != 0
    assert "No registered Windows project" in missing.output
    assert not events

    assert (
        CliRunner()
        .invoke(app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)])
        .exit_code
        == 0
    )
    events.clear()
    already_on = CliRunner().invoke(app, ["cloud", "enable"])
    assert already_on.exit_code == 0
    assert "Connector:" in already_on.output
    assert not events

    monkeypatch.setattr(cloud_windows_user_cli, "local_state", lambda: "Off")
    monkeypatch.setattr(cloud_windows_user_cli.typer, "confirm", lambda *_a, **_kw: False)
    cancelled = CliRunner().invoke(app, ["cloud", "enable"])
    assert cancelled.exit_code == 0
    assert "remains Off" in cancelled.output
    assert not events
    monkeypatch.setattr(cloud_windows_user_cli.typer, "confirm", lambda *_a, **_kw: True)
    activated = CliRunner().invoke(app, ["cloud", "enable"])
    assert activated.exit_code == 0
    assert "Connector scheduled" in activated.output
    assert events == ["schedule"]


def test_windows_status_and_disable_fail_closed_for_unverifiable_state(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    _folder, _events, _project, _selected = windows_cli
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "selected_project",
        lambda: (_ for _ in ()).throw(OSError("corrupt state")),
    )
    bad_status = CliRunner().invoke(app, ["cloud", "status"])
    assert bad_status.exit_code == 1
    assert "needs repair" in bad_status.output

    monkeypatch.setattr(cloud_windows_user_cli, "disable_windows_connector", lambda: False)
    failed_stop = CliRunner().invoke(app, ["cloud", "disable"])
    assert failed_stop.exit_code == 1
    assert "not verified" in failed_stop.output
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "disable_windows_connector",
        lambda: (_ for _ in ()).throw(OSError("task scheduler unavailable")),
    )
    fail = CliRunner().invoke(app, ["cloud", "disconnect"])
    assert fail.exit_code != 0
    assert "could not be fully verified" in fail.output
