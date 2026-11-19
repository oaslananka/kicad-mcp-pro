"""Foreground Cloud command: no repeated pairing, authentic status, safe failure paths."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

from kicad_mcp import cloud_user_cli, cloud_windows_connector, cloud_windows_user_cli, server

_REAL_SETUP_WINDOWS = cloud_windows_user_cli.setup_windows


@pytest.fixture(autouse=True)
def _isolate_test_connector_mutex(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests use their own mutex, never the owner's running Connector."""
    from kicad_mcp import cloud_windows_single_instance

    monkeypatch.setattr(
        cloud_windows_single_instance,
        "_MUTEX_NAME",
        rf"Local\KiCadMcpProUnitTest_{uuid4().hex}",
    )


@pytest.fixture
def remote_fixture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[dict[str, Any], Path]:
    folder = tmp_path / "board"
    folder.mkdir()
    (folder / "demo.kicad_pro").touch()
    project = SimpleNamespace(origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN)
    selected = SimpleNamespace(filename_stem="demo", directory=folder)
    state = {"project": project, "calls": []}
    monkeypatch.setattr(cloud_user_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(cloud_windows_connector, "selected_project", lambda: state["project"])
    monkeypatch.setattr(
        cloud_windows_connector, "local_state", lambda: "Configured (not connected)"
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_local_selection.inspect_owner_selected_project", lambda _: selected
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_task_scheduler.stop_and_remove_owner_task",
        lambda: state["calls"].append("task_removed") or True,
    )

    async def run_connector(*, stop, status_callback):
        assert isinstance(stop, asyncio.Event)
        status_callback("Connecting")
        status_callback("Connected")
        state["calls"].append("foreground")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", run_connector)

    def setup_windows(**kwargs: object) -> None:
        state["calls"].append("paired")
        assert kwargs["start_background"] is False
        state["project"] = project

    monkeypatch.setattr("kicad_mcp.cloud_windows_user_cli.setup_windows", setup_windows)
    return state, folder


@pytest.mark.parametrize("argv", [["remote"], ["cloud", "remote"]])
def test_remote_reuses_existing_pairing(
    argv: list[str], remote_fixture: tuple[dict[str, Any], Path]
) -> None:
    state, _ = remote_fixture
    result = CliRunner().invoke(server.app, argv)
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["task_removed", "foreground"]
    assert "Cloud acknowledged" in result.output
    assert "Keep this terminal open" in result.output


def test_foreground_terminal_stream_distinguishes_tool_folder_network_and_errors(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _folder = remote_fixture

    async def emit_activity(*, stop, status_callback) -> None:
        assert isinstance(stop, asyncio.Event)
        for message in (
            "Connecting",
            "Connected",
            "Tool call 1: read started",
            "Tool call 1: project_summary completed (12 ms)",
            "Tool call 2: write failed",
            "Opening Windows project folder dialog",
            "Folder selection cancelled",
            "Cloud disconnected; reconnecting",
        ):
            status_callback(message)
        state["calls"].append("foreground")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", emit_activity)
    result = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["task_removed", "foreground"]
    for expected in (
        "CONNECT",
        "ONLINE",
        "TOOL",
        "FOLDER",
        "NETWORK",
        "read started",
        "project_summary completed (12 ms)",
        "write failed",
        "Folder selection cancelled",
        "Cloud disconnected",
    ):
        assert expected in result.output, expected
    assert "Manage projects:" in result.output


def test_second_owner_connector_is_explained_without_claiming_new_write_authority(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.cloud_windows_single_instance import CloudConnectorAlreadyRunningError

    state, _folder = remote_fixture

    async def duplicate_session(**_kwargs: object) -> None:
        raise CloudConnectorAlreadyRunningError(
            "Another Cloud Connector is already running in this Windows login. "
            "Stop its foreground terminal with Ctrl+C before starting a new session."
        )

    monkeypatch.setattr(cloud_windows_connector, "run_connector", duplicate_session)
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code == 2
    assert "Another Cloud Connector is already running" in response.output
    assert "Ctrl+C" in response.output
    assert "Signed native PCB editing enabled" not in response.output
    assert state["calls"] == ["task_removed"]


def test_native_write_duplicate_never_claims_editing_is_enabled(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp.cloud_windows_single_instance import CloudConnectorAlreadyRunningError

    state, _folder = remote_fixture
    issuer = Ed25519PrivateKey.generate().public_key()
    monkeypatch.setattr(
        cloud_user_cli, "_trusted_owner_write_issuer", lambda *_args, **_kwargs: issuer
    )

    async def blocked(**_kwargs: object) -> None:
        raise CloudConnectorAlreadyRunningError(
            "Another Cloud Connector is already running. Stop its terminal with Ctrl+C."
        )

    monkeypatch.setattr(cloud_windows_connector, "run_connector", blocked)
    response = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert response.exit_code == 2
    assert "Signed native PCB editing requested" in response.output
    assert "Not active until the signed Connector connects" in response.output
    assert "Signed native PCB editing enabled" not in response.output
    assert "Another Cloud Connector is already running" in response.output
    assert state["calls"] == ["task_removed"]


def test_duplicate_connector_cannot_touch_owner_task_or_saved_write_choice(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.cloud_windows_single_instance import CloudConnectorAlreadyRunningError

    state, _folder = remote_fixture
    calls: list[str] = []

    def reject_duplicate() -> None:
        calls.append("instance_lock")
        raise CloudConnectorAlreadyRunningError(
            "Another Cloud Connector is already running in this Windows login."
        )

    def prohibited_issuer(*_args: object, **_kwargs: object) -> None:
        calls.append("write_issuer")
        raise AssertionError("duplicate must not inspect owner write issuer")

    monkeypatch.setattr(cloud_user_cli, "owner_connector_instance", reject_duplicate)
    monkeypatch.setattr(cloud_user_cli, "_trusted_owner_write_issuer", prohibited_issuer)
    response = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert response.exit_code == 2
    assert "Another Cloud Connector" in response.output
    assert calls == ["instance_lock"]
    assert state["calls"] == [], "duplicate must not alter a running owner's scheduled task"


def test_first_pairing_chooses_folder_and_launches_foreground(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    state["project"] = None
    monkeypatch.setattr(cloud_user_cli, "_has_kicad_project_files", lambda _: False)
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["paired", "task_removed", "foreground"]


def test_unverifiable_task_never_starts_duplicate_session(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_task_scheduler.stop_and_remove_owner_task", lambda: False
    )
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert state["calls"] == []
    assert "Could not stop" in result.output


def test_different_folder_does_not_override_pairing(
    remote_fixture: tuple[dict[str, Any], Path], tmp_path: Path
) -> None:
    state, _ = remote_fixture
    other = tmp_path / "other"
    other.mkdir()
    (other / "other.kicad_pro").touch()
    result = CliRunner().invoke(server.app, ["remote", "--project-dir", str(other)])
    assert result.exit_code != 0
    assert state["calls"] == []
    assert "already paired" in result.output


def test_noninteractive_unpaired_session_rejected_before_mutation(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr("kicad_mcp.cloud_windows_connector.selected_project", lambda: None)
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert state["calls"] == []


def test_remote_rejects_unsupported_operating_system_before_change(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(cloud_user_cli, "_is_windows", lambda: False)
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert "supported on Windows" in result.output
    assert state["calls"] == []


def test_remote_rejects_ambiguous_folder_selection(
    remote_fixture: tuple[dict[str, Any], Path],
) -> None:
    state, folder = remote_fixture
    result = CliRunner().invoke(server.app, ["remote", "--browse", "--project-dir", str(folder)])
    assert result.exit_code != 0
    # Rich can truncate the pretty-printed message, so assert the precise
    # validation contract without depending on terminal width or ANSI output.
    assert "browse" in result.output
    with pytest.raises(typer.BadParameter, match=r"Use --browse or --project-dir, not both"):
        cloud_user_cli.remote(
            browse=True,
            project_dir=folder,
            cloud_origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
            no_browser=False,
        )
    assert state["calls"] == []


def test_cancelled_first_pairing_never_starts_a_connector(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    state["project"] = None
    monkeypatch.setattr(
        "kicad_mcp.cloud_windows_user_cli.setup_windows",
        lambda **_kwargs: state["calls"].append("pairing_cancelled"),
    )
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code == 0
    assert "Pairing cancelled" in result.output
    assert state["calls"] == ["pairing_cancelled"]


def test_existing_pairing_cannot_change_cloud_origin(
    remote_fixture: tuple[dict[str, Any], Path],
) -> None:
    state, _ = remote_fixture
    state["project"].origin = "https://another.example"
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert "different Cloud site" in result.output
    assert state["calls"] == []


def test_remote_activates_a_disabled_local_connector(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(cloud_windows_connector, "local_state", lambda: "Off")
    monkeypatch.setattr(
        cloud_windows_connector,
        "activate",
        lambda _project, *, owner_confirm: (
            state["calls"].append("activate") if owner_confirm(state["project"]) else None
        ),
    )
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["task_removed", "activate", "foreground"]


def test_remote_does_not_start_when_local_marker_needs_repair(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(cloud_windows_connector, "local_state", lambda: "Unavailable")
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert "requires repair" in result.output
    assert state["calls"] == ["task_removed"]


def test_foreground_setup_reuses_exact_owner_project_without_registering(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, folder = remote_fixture
    project = state["project"]
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "_choose_project",
        lambda _path, *, browse, picker: (folder, "demo"),
    )
    monkeypatch.setattr(cloud_windows_user_cli, "selected_project", lambda: project)
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "inspect_owner_selected_project",
        lambda _project: SimpleNamespace(directory=folder, filename_stem="demo"),
    )
    _REAL_SETUP_WINDOWS(
        origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
        alias="Lab",
        project_dir=folder,
        browse=False,
        new_device=False,
        approval=lambda *_args: pytest.fail("must not enroll again"),
        picker=lambda: folder,
        owner_terminal=lambda: True,
        start_background=False,
    )
    assert state["calls"] == []


def test_foreground_setup_rejects_different_project_without_mutation(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, folder = remote_fixture
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "_choose_project",
        lambda _path, *, browse, picker: (folder, "different"),
    )
    monkeypatch.setattr(cloud_windows_user_cli, "selected_project", lambda: state["project"])
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "inspect_owner_selected_project",
        lambda _project: SimpleNamespace(directory=folder, filename_stem="demo"),
    )
    with pytest.raises(Exception, match="different project"):
        _REAL_SETUP_WINDOWS(
            origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
            alias="Lab",
            project_dir=folder,
            browse=False,
            new_device=False,
            approval=lambda *_args: pytest.fail("must not enroll again"),
            picker=lambda: folder,
            owner_terminal=lambda: True,
            start_background=False,
        )
    assert state["calls"] == []


def test_remote_policy_rejection_exits_with_actionable_status_no_traceback(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _folder = remote_fixture

    async def denied(*, stop, status_callback) -> None:
        status_callback(
            "Cloud rejected this device session (policy 1008). "
            "Review pairing at https://kicad-mcp-pro.oaslananka.dev/devices. "
            "The local project and saved credentials were not changed."
        )
        raise cloud_windows_connector.CloudOwnerReapprovalRequiredError("test-only")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", denied)
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code == 3, result.output
    assert "policy 1008" in result.output
    assert "/devices" in result.output
    assert "Traceback" not in result.output
    assert state["calls"] == ["task_removed"]


@pytest.mark.parametrize("invalid", ["no-saved-device", "foreign-cloud", "changed-folder"])
def test_device_repair_fails_closed_without_changing_existing_project(
    remote_fixture: tuple[dict[str, Any], Path], invalid: str
) -> None:
    state, folder = remote_fixture
    if invalid == "no-saved-device":
        state["project"] = None
    elif invalid == "foreign-cloud":
        state["project"].origin = "https://other-cloud.example"
    path = folder if invalid == "changed-folder" else None
    with pytest.raises(typer.BadParameter):
        cloud_user_cli._select_remote_project(
            cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
            browse=False,
            project_dir=path,
            no_browser=False,
            repair_device=True,
        )
    assert state["calls"] == []


def test_explicit_device_repair_routes_through_browser_owner_approval(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    approved: list[str] = []

    def repaired(previous: object, **args: object) -> object:
        assert previous == state["project"]
        assert args["origin"] == cloud_user_cli.DEFAULT_CLOUD_ORIGIN
        assert callable(args["approval"])
        assert callable(args["stop_previous"])
        approved.append("owner-browser-repair")
        return previous

    monkeypatch.setattr(cloud_windows_user_cli, "repair_windows_project", repaired)
    result = cloud_user_cli._select_remote_project(
        cloud_user_cli.DEFAULT_CLOUD_ORIGIN, False, None, False, True
    )
    assert result == state["project"]
    assert approved == ["owner-browser-repair"]
    assert state["calls"] == []


def test_native_drc_requires_a_foreground_opt_in_on_the_actual_remote_command(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _folder = remote_fixture

    async def native(*, stop: asyncio.Event, status_callback, allow_native_drc: bool) -> None:
        assert isinstance(stop, asyncio.Event)
        assert allow_native_drc is True
        status_callback("Connected")
        state["calls"].append("native-drc")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", native)
    result = CliRunner().invoke(server.app, ["remote", "--allow-native-drc"])
    assert result.exit_code == 0, result.output
    assert "Read-only native DRC allowed" in result.output
    assert state["calls"] == ["task_removed", "native-drc"]


def test_explicit_owner_write_opt_in_forwards_only_pinned_issuer(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_windows_write_issuer

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    key = Ed25519PrivateKey.generate().public_key()
    captured: list[dict[str, object]] = []

    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "load_pinned_windows_write_issuer_key",
        lambda record: key if record == "a" * 32 else None,
    )
    from kicad_mcp import cloud_windows_write_marker

    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: _folder,
    )

    async def foreground(**options: object) -> None:
        captured.append(options)

    monkeypatch.setattr(cloud_windows_connector, "run_connector", foreground)
    result = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["task_removed"]
    assert len(captured) == 1
    assert captured[0]["allow_native_write"] is True
    assert captured[0]["issuer_key"] is key
    assert captured[0]["allow_native_drc"] is False
    assert "Cloud still requires separate client and project edit permission" in result.output


def test_owner_remembers_editing_once_and_reuses_it_in_future_foreground_sessions(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import (
        cloud_windows_write_issuer,
        cloud_windows_write_marker,
        cloud_windows_write_preference,
    )

    state, folder = remote_fixture
    state["project"].record_id = "a" * 32
    state["project"].project_id = "22222222-2222-4222-8222-222222222222"
    key = Ed25519PrivateKey.generate().public_key()
    remembered: set[str] = set()
    executions: list[dict[str, object]] = []
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "load_pinned_windows_write_issuer_key",
        lambda record: key if record == "a" * 32 else None,
    )
    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: folder,
    )
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "owner_native_write_remembered",
        lambda _record, project: project in remembered,
    )
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "remember_owner_native_write",
        lambda _record, project: remembered.add(project),
    )

    async def foreground(**options: object) -> None:
        executions.append(options)

    monkeypatch.setattr(cloud_windows_connector, "run_connector", foreground)
    first = CliRunner().invoke(
        server.app, ["cloud", "remote", "--enable-native-write", "--remember-native-write"]
    )
    assert first.exit_code == 0, first.output
    assert len(remembered) == 1
    second = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert second.exit_code == 0, second.output
    assert len(executions) == 2
    assert all(run["allow_native_write"] is True for run in executions)
    assert all(run["issuer_key"] is key for run in executions)


def test_owner_forgets_saved_edit_preference_without_removing_issuer(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_preference

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    state["project"].project_id = "22222222-2222-4222-8222-222222222222"
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "forget_owner_native_write",
        lambda record, project: calls.append((record, project)) or True,
    )
    result = CliRunner().invoke(server.app, ["cloud", "forget-native-write"])
    assert result.exit_code == 0, result.output
    assert calls == [("a" * 32, state["project"].project_id)]
    assert "next" in result.output.lower()


def test_remote_missing_pinned_issuer_does_not_touch_owner_task_or_project(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "load_pinned_windows_write_issuer_key",
        lambda _record: (_ for _ in ()).throw(LocalWriteDeniedError("request denied")),
    )
    result = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert result.exit_code != 0
    assert "owner-pinned Cloud write issuer" in result.output
    assert state["calls"] == []


def test_remote_write_opt_in_rejects_noninteractive_even_if_pairing_exists(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _folder = remote_fixture
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    result = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert result.exit_code != 0
    assert state["calls"] == []


def test_write_opt_in_rejects_untrusted_marker_storage_before_owner_task(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_windows_write_issuer, cloud_windows_write_marker
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "load_pinned_windows_write_issuer_key",
        lambda _record: Ed25519PrivateKey.generate().public_key(),
    )
    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: (_ for _ in ()).throw(LocalWriteDeniedError("request denied")),
    )
    result = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert result.exit_code != 0
    assert "replay" in result.output.casefold()
    assert state["calls"] == []


def test_saved_owner_write_preference_read_error_fails_closed(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_preference

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    state["project"].project_id = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "owner_native_write_remembered",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("vault unavailable")),
    )
    result = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert result.exit_code != 0
    assert "Saved local editing permission" in result.output
    assert state["calls"] == []


def test_owner_write_preference_save_failure_never_starts_connector(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import (
        cloud_windows_write_issuer,
        cloud_windows_write_marker,
        cloud_windows_write_preference,
    )

    state, folder = remote_fixture
    state["project"].record_id = "a" * 32
    state["project"].project_id = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(
        cloud_windows_write_issuer,
        "load_pinned_windows_write_issuer_key",
        lambda _record: Ed25519PrivateKey.generate().public_key(),
    )
    monkeypatch.setattr(
        cloud_windows_write_marker,
        "prepare_owner_windows_write_marker_directory",
        lambda: folder,
    )
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "remember_owner_native_write",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("vault locked")),
    )
    result = CliRunner().invoke(
        server.app, ["cloud", "remote", "--enable-native-write", "--remember-native-write"]
    )
    assert result.exit_code != 0
    assert "Could not save" in result.output
    assert state["calls"] == []


def test_forget_owner_write_preference_requires_interactive_windows_owner(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _folder = remote_fixture
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    result = CliRunner().invoke(server.app, ["cloud", "forget-native-write"])
    assert result.exit_code != 0
    assert "interactive Windows" in result.output
    assert state["calls"] == []


def test_forget_owner_write_preference_requires_existing_pairing(
    remote_fixture: tuple[dict[str, Any], Path],
) -> None:
    state, _folder = remote_fixture
    state["project"] = None
    result = CliRunner().invoke(server.app, ["cloud", "forget-native-write"])
    assert result.exit_code != 0
    assert "No locally paired" in result.output
    assert state["calls"] == []


def test_forget_owner_write_preference_rejects_tampered_store(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_preference
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

    state, _folder = remote_fixture
    state["project"].record_id = "a" * 32
    state["project"].project_id = "22222222-2222-4222-8222-222222222222"
    monkeypatch.setattr(
        cloud_windows_write_preference,
        "forget_owner_native_write",
        lambda *_args: (_ for _ in ()).throw(LocalWriteDeniedError("request denied")),
    )
    result = CliRunner().invoke(server.app, ["cloud", "forget-native-write"])
    assert result.exit_code != 0
    assert "could not be verified" in result.output
    assert state["calls"] == []


@pytest.mark.parametrize(
    "message, category",
    [
        ("Connecting", "CONNECT"),
        ("Connected", "ONLINE"),
        ("Tool call 1: run_drc completed", "TOOL"),
        ("Opening Windows project folder dialog", "FOLDER"),
        ("Cloud disconnected; reconnecting", "NETWORK"),
    ],
)
def test_cloud_status_cp1252_output_never_crashes_connector(
    monkeypatch: pytest.MonkeyPatch, message: str, category: str
) -> None:
    # Windows redirected stdout often uses a non-UTF-8 code page.
    import io

    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(cloud_user_cli.sys, "stdout", stream)

    cloud_user_cli._display_cloud_status(message, cloud_user_cli.DEFAULT_CLOUD_ORIGIN)

    rendered = output.getvalue().decode("cp1252")
    assert category in rendered
    assert message == "Connected" or message in rendered
    assert rendered.encode("cp1252") == output.getvalue()


def test_cloud_banner_divider_uses_ascii_only_for_cp1252(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    output = io.BytesIO()
    stream = io.TextIOWrapper(output, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(cloud_user_cli.sys, "stdout", stream)

    assert cloud_user_cli._cloud_console_glyph("\u2500" * 40, "-" * 40) == "-" * 40


def test_cloud_console_keeps_unicode_when_output_supports_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import io

    stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", write_through=True)
    monkeypatch.setattr(cloud_user_cli.sys, "stdout", stream)

    assert cloud_user_cli._cloud_console_glyph("\u2500" * 40, "-" * 40) == "\u2500" * 40
