"""Windows terminal onboarding contract: no real browser, Cloud or scheduled task."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from kicad_mcp import cloud_user_cli, cloud_windows_user_cli
from kicad_mcp.cloud_windows_enrollment import (
    WindowsEnrolledDevice,
    WindowsEnrollmentError,
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
        assert the_project == project
        assert path == folder
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
    assert result.exit_code == 0
    assert "Setup paused" in result.output
    assert "cloud setup --browse" in result.output
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


def test_windows_registration_failure_includes_diagnostic_details(
    windows_cli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder, events, _project, _selected = windows_cli

    def server_rejection(**_kwargs: object) -> None:
        raise WindowsEnrollmentError(
            "Windows device enrollment could not be completed. "
            "(Pairing request failed: HTTP 403: untrusted_ingress)"
        )

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", server_rejection)
    result = CliRunner().invoke(
        app,
        ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)],
        terminal_width=200,
    )
    assert result.exit_code != 0
    assert "Windows Cloud registration was not fully completed" in result.output
    assert "HTTP 403: untrusted_ingress" in result.output
    assert "Review your Cloud Devices page" in result.output
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


def test_windows_status_includes_running_state_when_active(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, _events, _project, _selected = windows_cli
    CliRunner().invoke(app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)])
    monkeypatch.setattr(
        cloud_windows_user_cli, "scheduler_state", lambda: "Scheduled (connection unverified)"
    )
    monkeypatch.setattr(cloud_windows_user_cli, "task_run_state", lambda: "Running")
    status = CliRunner().invoke(app, ["cloud", "status"])
    assert status.exit_code == 0
    assert "Scheduled (connection unverified) [Running]" in status.output


def test_windows_status_missing_legacy_task_explains_foreground_remote(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, _events, _project, _selected = windows_cli
    first = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert first.exit_code == 0, first.output
    monkeypatch.setattr(
        cloud_windows_user_cli, "scheduler_state", lambda: "Configured (task unverified)"
    )
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "task_run_state",
        lambda: (_ for _ in ()).throw(AssertionError("do not query absent task")),
    )

    status = CliRunner().invoke(app, ["cloud", "status"])
    assert status.exit_code == 0, status.output
    assert "No verified background task" in status.output
    assert "foreground Cloud session may still be active" in status.output
    assert "kicad-mcp-pro remote (keep this terminal open)" in status.output
    assert "Connected" not in status.output
    assert "Cloud owner grants/revocation" in status.output


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


def test_foreground_remote_pairing_uses_browser_consent_without_second_terminal_prompt(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli

    def activate_local(project: WindowsRegisteredProject, *, owner_confirm) -> None:
        assert owner_confirm(project) is True
        events.append("foreground_activate")

    monkeypatch.setattr("kicad_mcp.cloud_windows_connector.activate", activate_local)
    cloud_windows_user_cli.setup_windows(
        origin=ORIGIN,
        alias="Lab PC",
        project_dir=folder,
        browse=False,
        new_device=False,
        approval=lambda _page, _challenge, _code: events.append("browser_approval"),
        picker=lambda: folder,
        owner_terminal=lambda: True,
        start_background=False,
    )
    assert events == [
        "enroll",
        "browser_approval",
        "register",
        "bind",
        "remember",
        "foreground_activate",
    ]
    assert "owner_confirm" not in events
    assert "schedule" not in events


def test_windows_reconnect_repairs_verified_missing_task_without_repairing(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli
    initial = CliRunner().invoke(
        app, ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    )
    assert initial.exit_code == 0, initial.output
    events.clear()
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "scheduler_state",
        lambda: "Configured (task unverified)",
    )

    recovered = CliRunner().invoke(app, ["cloud", "reconnect"])
    assert recovered.exit_code == 0, recovered.output
    assert events == ["owner_confirm", "disable", "schedule"]
    assert "task restored" in recovered.output.lower()
    assert "connected" not in recovered.output.lower()


def test_windows_reconnect_cancel_missing_task_keeps_registration(
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
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "scheduler_state",
        lambda: "Configured (task unverified)",
    )
    monkeypatch.setattr(cloud_windows_user_cli.typer, "confirm", lambda *_a, **_k: False)
    declined = CliRunner().invoke(app, ["cloud", "reconnect"])
    assert declined.exit_code == 0, declined.output
    assert "unchanged" in declined.output.lower()
    assert not events


def test_windows_reconnect_missing_task_refuses_unverified_stop(
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
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "scheduler_state",
        lambda: "Configured (task unverified)",
    )
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "disable_windows_connector",
        lambda: events.append("stop-not-verified") or False,
    )
    refused = CliRunner().invoke(app, ["cloud", "reconnect"])
    assert refused.exit_code != 0
    assert "not verified" in refused.output.lower()
    assert events == ["owner_confirm", "stop-not-verified"]


def test_windows_existing_setup_restores_missing_task_without_pairing(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder, events, _project, _selected = windows_cli
    args = ["cloud", "setup", "--alias", "Lab PC", "--project-dir", str(folder)]
    assert CliRunner().invoke(app, args).exit_code == 0
    events.clear()
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "scheduler_state",
        lambda: "Configured (task unverified)",
    )

    repaired = CliRunner().invoke(app, args)
    assert repaired.exit_code == 0, repaired.output
    assert events == ["owner_confirm", "disable", "schedule"]
    assert "task restored" in repaired.output.lower()
    assert "No new device registration" in repaired.output


def test_windows_reconnect_unverifiable_task_never_replaces_scheduler_entry(
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
    monkeypatch.setattr(cloud_windows_user_cli, "scheduler_state", lambda: "Unavailable")
    result = CliRunner().invoke(app, ["cloud", "reconnect"])
    assert result.exit_code == 0
    assert "Unavailable" in result.output
    assert events == []


def test_remote_exposes_explicit_repair_command_without_running_pairing() -> None:
    from typer.main import get_command

    options = CliRunner().invoke(app, ["cloud", "remote", "--help"])
    assert options.exit_code == 0, options.output
    # Rich inserts ANSI escapes within option text on Windows. Inspect the
    # registered Click options, not presentation-dependent terminal bytes.
    remote_command = get_command(cloud_user_cli.cloud_app).commands["remote"]
    option_names = {
        name for parameter in remote_command.params for name in getattr(parameter, "opts", ())
    }
    assert "--repair-device" in option_names
    assert "--allow-native-drc" in option_names


def test_browser_approved_device_repair_reuses_project_and_preserves_old_binding(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_connector

    folder, events, previous, selection = windows_cli
    new_device = WindowsEnrolledDevice(
        record_id="d" * 32,
        origin=previous.origin,
        owner_sub=previous.owner_sub,
        device_id="f9ee4be9-0aec-448e-9873-721ae113ec02",
        fingerprint="d" * 64,
    )
    replacement = WindowsRegisteredProject(
        registration_id="c" * 32,
        record_id=new_device.record_id,
        origin=previous.origin,
        owner_sub=previous.owner_sub,
        device_id=new_device.device_id,
        fingerprint=new_device.fingerprint,
        project_id="e9ee4be9-0aec-448e-9873-721ae113ec02",
        filename_stem=previous.filename_stem,
    )

    def enroll(**options: object) -> WindowsEnrolledDevice:
        events.append("fresh-pairing")
        approval = options["owner_approval"]
        assert callable(approval)
        approval(ORIGIN + "/devices/pairing", "challenge", "TEST-CODE")
        return new_device

    def register(paired: WindowsEnrolledDevice, **options: object) -> WindowsRegisteredProject:
        events.append("fresh-project")
        assert paired == new_device
        assert options["filename_stem"] == previous.filename_stem
        return replacement

    def bind(project, directory, *, owner_confirm):
        events.append("bind-same-folder")
        assert project == replacement and directory == folder
        assert owner_confirm(directory) is True
        return selection

    def switch(old, new, *, owner_confirm):
        events.append("switch")
        assert old == previous and new == replacement and owner_confirm(old, new) is True

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", enroll)
    monkeypatch.setattr(cloud_windows_user_cli, "register_windows_project", register)
    monkeypatch.setattr(cloud_windows_user_cli, "bind_owner_selected_project", bind)
    monkeypatch.setattr(cloud_windows_connector, "repair_selected_project", switch)

    got = cloud_windows_user_cli.repair_windows_project(
        previous,
        origin=ORIGIN,
        alias="Lab PC",
        approval=lambda *_args: events.append("browser-approval"),
        stop_previous=lambda: events.append("stop-old") or True,
    )
    assert got == replacement
    assert events == [
        "fresh-pairing",
        "browser-approval",
        "fresh-project",
        "bind-same-folder",
        "stop-old",
        "switch",
    ]
    assert selection.directory == folder


def test_repair_requires_verified_old_connector_stop_before_selection_switch(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_connector

    folder, events, previous, _selection = windows_cli

    def unsafe_switch(*_args: object, **_kwargs: object) -> None:
        pytest.fail("old active Connector was not stopped; never switch credentials")

    monkeypatch.setattr(cloud_windows_connector, "repair_selected_project", unsafe_switch)
    with pytest.raises(Exception, match="previous local selection was preserved"):
        cloud_windows_user_cli.repair_windows_project(
            previous,
            origin=ORIGIN,
            alias="Lab PC",
            approval=lambda *_args: events.append("browser-approval"),
            stop_previous=lambda: False,
        )
    assert "browser-approval" in events
    assert previous.filename_stem == "demo" and folder.is_dir()


def test_repair_rejects_foreign_cloud_before_reenrollment(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    _folder, events, old, _selection = windows_cli
    with pytest.raises(cloud_windows_user_cli.typer.BadParameter, match="trusted Cloud origin"):
        cloud_windows_user_cli.repair_windows_project(
            old,
            origin="https://foreign-cloud.example",
            alias="Lab PC",
            approval=lambda *_: pytest.fail("no browser side effect"),
            stop_previous=lambda: pytest.fail("no task side effect"),
        )
    assert events == []


def test_repair_failed_owner_browser_pairing_retains_previous_selection(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    _folder, events, old, _selection = windows_cli

    def failed_enroll(**_opts: object) -> WindowsEnrolledDevice:
        raise RuntimeError("browser declined")

    monkeypatch.setattr(cloud_windows_user_cli, "enroll_windows_device", failed_enroll)
    with pytest.raises(cloud_windows_user_cli.typer.BadParameter, match="not completed"):
        cloud_windows_user_cli.repair_windows_project(
            old,
            origin=ORIGIN,
            alias="Lab PC",
            approval=lambda *_: events.append("owner-browser"),
            stop_previous=lambda: pytest.fail("must not stop old task"),
        )
    assert events == []


def test_repair_cannot_claim_success_after_new_pairing_if_local_switch_fails(
    windows_cli, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_connector

    _folder, events, old, _selection = windows_cli

    def unsafe_switch(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated credential manager write failure")

    monkeypatch.setattr(cloud_windows_connector, "repair_selected_project", unsafe_switch)
    with pytest.raises(
        cloud_windows_user_cli.typer.BadParameter, match="could not be switched safely"
    ):
        cloud_windows_user_cli.repair_windows_project(
            old,
            origin=ORIGIN,
            alias="Lab PC",
            approval=lambda *_: events.append("browser-approval"),
            stop_previous=lambda: events.append("stop-old") or True,
        )
    assert events == ["enroll", "browser-approval", "register", "bind", "stop-old"]
