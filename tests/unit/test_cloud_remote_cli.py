"""Foreground Cloud command: no repeated pairing, authentic status, safe failure paths."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from kicad_mcp import cloud_user_cli, cloud_windows_connector, server


@pytest.fixture()
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


def test_noninteractive_session_rejected_before_mutation(
    remote_fixture: tuple[dict[str, Any], Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    state, _ = remote_fixture
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    result = CliRunner().invoke(server.app, ["remote"])
    assert result.exit_code != 0
    assert state["calls"] == []
