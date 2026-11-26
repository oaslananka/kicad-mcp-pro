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


def test_default_cloud_on_unpaired_windows_identity_uses_one_owner_browser_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_user_cli as owner_cli
    from kicad_mcp import cloud_windows_connector as connector

    calls: list[str] = []
    monkeypatch.setattr(owner_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(connector, "selected_project", lambda: None)
    monkeypatch.setattr(
        owner_cli,
        "_connect_unbound_windows_device",
        lambda _origin, _alias: calls.append("browser_then_folder") or False,
    )
    monkeypatch.setattr(
        owner_cli,
        "_connect_windows_foreground",
        lambda *_args, **_kwargs: calls.append("existing_project"),
    )
    result = CliRunner().invoke(server.app, ["cloud"])
    assert result.exit_code == 0, result.output
    assert calls == ["browser_then_folder"]


def test_default_cloud_command_reuses_device_without_implicit_native_write(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer

    state, _ = remote_fixture
    state["project"] = SimpleNamespace(
        origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN, record_id="a" * 32
    )
    called: list[object] = []

    def approve(record: str, *, origin: str) -> None:
        assert record == "a" * 32
        assert origin == cloud_user_cli.DEFAULT_CLOUD_ORIGIN
        called.append("bundled_owner_issuer")

    monkeypatch.setattr(issuer, "trust_bundled_owner_cloud_issuer", approve)

    def connect(*_args: object, **kwargs: object) -> None:
        called.append(("foreground", kwargs["allow_native_write"], kwargs["new_device"]))

    monkeypatch.setattr(cloud_user_cli, "_connect_windows_foreground", connect)
    response = CliRunner().invoke(server.app, ["cloud"])
    assert response.exit_code == 0, response.output
    assert called == [("foreground", False, False)]
    assert state["calls"] == [], "No new pairing or background task requested"


def test_broken_owner_issuer_does_not_block_readonly_default_connection(
    remote_fixture: tuple[dict[str, Any], Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_write_issuer as issuer
    from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

    state, _ = remote_fixture
    state["project"] = SimpleNamespace(
        origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN, record_id="a" * 32
    )
    monkeypatch.setattr(
        issuer,
        "trust_bundled_owner_cloud_issuer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(LocalWriteDeniedError("denied")),
    )

    def connect_readonly(*_args: object, **kwargs: object) -> None:
        state["calls"].append(("foreground", kwargs["allow_native_write"]))

    monkeypatch.setattr(cloud_user_cli, "_connect_windows_foreground", connect_readonly)
    result = CliRunner().invoke(server.app, ["cloud"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == [("foreground", False)]


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
            "Opening local project folder dialog",
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
        ("Opening local project folder dialog", "FOLDER"),
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


def test_foreground_restores_previously_enabled_background_connector_after_lock_release(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A temporary terminal must not permanently remove the owner's existing service."""
    from contextlib import contextmanager

    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    state, _ = remote_fixture
    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Scheduled (connection unverified)")

    @contextmanager
    def owner_lock():
        state["calls"].append("lock_acquired")
        try:
            yield
        finally:
            state["calls"].append("lock_released")

    monkeypatch.setattr(cloud_user_cli, "owner_connector_instance", owner_lock)

    def restore_readonly(project, *, owner_confirm):
        assert project is state["project"]
        assert owner_confirm(project) is True
        state["calls"].append("read_only_task_restored")

    monkeypatch.setattr(scheduler, "enable_windows_connector", restore_readonly)
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code == 0, response.output
    assert state["calls"] == [
        "lock_acquired",
        "task_removed",
        "foreground",
        "lock_released",
        "read_only_task_restored",
    ]
    assert "read-only background Connector" in response.output


def test_foreground_without_prior_task_never_installs_background_connector(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    state, _ = remote_fixture
    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Configured (task unverified)")
    monkeypatch.setattr(
        scheduler,
        "enable_windows_connector",
        lambda *_args, **_kwargs: pytest.fail("must not add a background service"),
    )
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code == 0, response.output
    assert state["calls"] == ["task_removed", "foreground"]


def test_restoration_failure_is_visible_and_never_claims_cloud_online(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Scheduled (connection unverified)")

    def unable_to_restore(*_args: object, **_kwargs: object) -> None:
        raise OSError("scheduler unavailable")

    monkeypatch.setattr(scheduler, "enable_windows_connector", unable_to_restore)
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code != 0
    assert "background Connector could not be restored" in response.output
    assert "cloud reconnect" in response.output


def test_scheduled_read_only_task_restored_after_foreground_native_write(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A signed edit in the terminal must never turn the background task into WRITE."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    state, _ = remote_fixture
    key = Ed25519PrivateKey.generate().public_key()
    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Scheduled (connection unverified)")
    monkeypatch.setattr(
        cloud_user_cli, "_trusted_owner_write_issuer", lambda *_args, **_kwargs: key
    )
    observed = []

    async def native(*, stop, status_callback, allow_native_write, issuer_key, allow_native_drc):
        assert allow_native_write is True
        assert issuer_key is key
        assert allow_native_drc is False
        observed.append("foreground_signed_write")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", native)

    def restore_read_only(project, *, owner_confirm):
        assert project is state["project"]
        assert owner_confirm(project) is True
        observed.append("read_only_task")

    monkeypatch.setattr(scheduler, "enable_windows_connector", restore_read_only)
    response = CliRunner().invoke(server.app, ["cloud", "remote", "--enable-native-write"])
    assert response.exit_code == 0, response.output
    assert observed == ["foreground_signed_write", "read_only_task"]


def test_disabled_owner_marker_is_not_reenabled_by_foreground_handoff(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    state, _ = remote_fixture
    marker = {"value": "Configured (not connected)"}
    monkeypatch.setattr(cloud_windows_connector, "local_state", lambda: marker["value"])
    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Scheduled (connection unverified)")
    monkeypatch.setattr(
        scheduler,
        "enable_windows_connector",
        lambda *_args, **_kwargs: pytest.fail("cannot restore a disabled service"),
    )

    async def owner_disables_connector(*, stop, status_callback):
        marker["value"] = "Off"
        state["calls"].append("owner_disabled")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", owner_disables_connector)
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code == 0, response.output
    assert state["calls"] == ["task_removed", "owner_disabled"]
    assert "not restored" in response.output


def test_ctrl_c_restores_previous_read_only_task_without_repairing(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_windows_task_scheduler as scheduler

    state, _ = remote_fixture
    monkeypatch.setattr(scheduler, "scheduler_state", lambda: "Scheduled (connection unverified)")

    async def interrupted(*, stop: asyncio.Event, status_callback) -> None:
        state["calls"].append("ctrl_c")
        raise KeyboardInterrupt

    def restore(project: object, *, owner_confirm) -> None:
        assert project is state["project"]
        assert owner_confirm(project)
        state["calls"].append("read_only_task_restored")

    monkeypatch.setattr(cloud_windows_connector, "run_connector", interrupted)
    monkeypatch.setattr(scheduler, "enable_windows_connector", restore)
    response = CliRunner().invoke(server.app, ["cloud", "remote"])
    assert response.exit_code == 0, response.output
    assert state["calls"] == ["task_removed", "ctrl_c", "read_only_task_restored"]
    assert "restoring previous read-only Connector" in response.output
    assert "Cloud connection not yet verified" in response.output


def test_unbound_cloud_pairs_once_then_reuses_identity_without_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_device_bootstrap as bootstrap
    from kicad_mcp import cloud_windows_enrollment as enrollment

    calls: list[str] = []
    current: dict[str, object] = {}
    device = enrollment.WindowsEnrolledDevice(
        record_id="a" * 32,
        origin=cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
        owner_sub="owner",
        device_id=str(uuid4()),
        fingerprint="a" * 64,
    )
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_resolve_device_alias", lambda _alias: "My PC")
    monkeypatch.setattr(
        cloud_user_cli, "_perform_approval", lambda *_args: calls.append("browser_approval")
    )
    monkeypatch.setattr(bootstrap, "selected_device", lambda: current.get("device"))

    def remember(value):
        current["device"] = value
        calls.append("remember_device")

    def enroll(*, origin, alias, owner_approval):
        assert origin == device.origin
        assert alias == "My PC"
        calls.append("enroll")
        owner_approval("https://example.invalid/pair", "challenge", "code")
        return device

    async def serve(value, *, status_callback):
        assert value is device
        calls.append("signed_connection")
        status_callback("Connected")

    monkeypatch.setattr(bootstrap, "remember_device", remember)
    monkeypatch.setattr(enrollment, "enroll_windows_device", enroll)
    monkeypatch.setattr(bootstrap, "run_device_only", serve)
    monkeypatch.setattr(
        cloud_user_cli, "_display_cloud_status", lambda event, _origin: calls.append(event)
    )
    assert cloud_user_cli._connect_unbound_windows_device(device.origin, "PC") is True
    assert cloud_user_cli._connect_unbound_windows_device(device.origin, "PC") is True
    assert calls == [
        "enroll",
        "browser_approval",
        "remember_device",
        "signed_connection",
        "Connected",
        "signed_connection",
        "Connected",
    ]


def test_unbound_cloud_fails_without_owner_terminal_or_with_different_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_device_bootstrap as bootstrap

    origin = cloud_user_cli.DEFAULT_CLOUD_ORIGIN
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    with pytest.raises(typer.BadParameter, match="interactive owner terminal"):
        cloud_user_cli._connect_unbound_windows_device(origin, "PC")
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(
        bootstrap, "selected_device", lambda: SimpleNamespace(origin="https://other.example")
    )
    with pytest.raises(typer.BadParameter, match="different origin"):
        cloud_user_cli._connect_unbound_windows_device(origin, "PC")


def test_unbound_cloud_denied_pairing_never_opens_signed_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp import cloud_windows_device_bootstrap as bootstrap
    from kicad_mcp import cloud_windows_enrollment as enrollment

    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(bootstrap, "selected_device", lambda: None)

    def rejected(**_kwargs: object) -> None:
        raise enrollment.WindowsEnrollmentError("Owner denied pairing")

    async def must_not_connect(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Denied enrollment must not open signed session")

    monkeypatch.setattr(enrollment, "enroll_windows_device", rejected)
    monkeypatch.setattr(bootstrap, "run_device_only", must_not_connect)
    with pytest.raises(typer.BadParameter, match="Owner denied pairing"):
        cloud_user_cli._connect_unbound_windows_device(
            cloud_user_cli.DEFAULT_CLOUD_ORIGIN,
            "PC",
        )


def test_repair_command_never_registers_old_project(remote_fixture, monkeypatch) -> None:
    from kicad_mcp import cloud_windows_device_bootstrap as bootstrap

    state, _ = remote_fixture
    monkeypatch.setattr(
        bootstrap,
        "repair_device_only",
        lambda **kwargs: state["calls"].append("device-only"),
        raising=False,
    )
    monkeypatch.setattr(
        cloud_windows_user_cli,
        "register_windows_project",
        lambda *_args, **_kwargs: pytest.fail("repair must not register a project"),
    )
    result = CliRunner().invoke(server.app, ["cloud", "remote", "--repair-device"])
    assert result.exit_code == 0, result.output
    assert state["calls"] == ["device-only"]
    assert "Add Project" in result.output


def test_repair_rejects_project_and_edit_options(remote_fixture, monkeypatch) -> None:
    from kicad_mcp import cloud_windows_device_bootstrap as bootstrap

    monkeypatch.setattr(
        bootstrap,
        "repair_device_only",
        lambda **kwargs: pytest.fail("must not pair"),
        raising=False,
    )
    for option in ("--browse", "--enable-native-write", "--allow-native-drc"):
        result = CliRunner().invoke(server.app, ["cloud", "remote", "--repair-device", option])
        assert result.exit_code != 0
        assert "repair" in result.output.lower()


@pytest.mark.parametrize("approved", [True, False])
def test_single_command_recovers_policy_failure_at_most_once(monkeypatch, approved) -> None:
    calls = []
    monkeypatch.setattr(cloud_user_cli, "_is_windows", lambda: True)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)

    def session() -> None:
        calls.append("session")
        raise typer.Exit(3)

    monkeypatch.setattr(cloud_user_cli, "_run_windows_cloud_session", session, raising=False)
    monkeypatch.setattr(
        cloud_user_cli,
        "_offer_device_recovery",
        lambda: calls.append("recover") or approved,
        raising=False,
    )
    result = CliRunner().invoke(server.app, ["cloud"])
    assert result.exit_code == 3
    assert calls == (["session", "recover", "session"] if approved else ["session", "recover"])
