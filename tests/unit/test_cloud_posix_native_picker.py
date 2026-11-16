"""Native POSIX folder chooser contract; tests never open any real UI."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp import cloud_posix_native_picker as picker


def test_linux_zenity_uses_argv_and_keeps_paths_local(monkeypatch, tmp_path: Path) -> None:
    directory = tmp_path / "KiCad Board"
    directory.mkdir()
    requests = []
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(
        picker.shutil, "which", lambda name: "/usr/bin/zenity" if name == "zenity" else None
    )

    def run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        requests.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=str(directory) + "\n", stderr="")

    monkeypatch.setattr(picker.subprocess, "run", run)
    assert picker.choose_project_folder() == directory
    assert requests[0][0] == [
        "/usr/bin/zenity",
        "--file-selection",
        "--directory",
        "--title=Choose your local KiCad project folder",
    ]
    assert requests[0][1]["shell"] is False
    assert requests[0][1]["timeout"] <= 120


def test_macos_osascript_cancellation_is_not_a_new_project(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="execution error: User canceled. (-128)"
        ),
    )
    assert picker.choose_project_folder() is None


def test_headless_linux_does_not_launch_any_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("No GUI process should be launched"),
    )
    assert picker.native_picker_available() is False
    with pytest.raises(OSError, match="graphical"):
        picker.choose_project_folder()


def test_macos_non_cancel_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="execution error: Permission denied. (-1743)"
        ),
    )
    with pytest.raises(OSError, match="folder chooser"):
        picker.choose_project_folder()


def test_linux_zenity_owner_cancel_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/zenity")
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    assert picker.choose_project_folder() is None


def test_macos_returns_owner_selected_local_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    folder = tmp_path / "KiCad Board"
    folder.mkdir()
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/osascript")
    monkeypatch.setattr(
        picker.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0, stdout=str(folder) + "\n", stderr=""
        ),
    )
    assert picker.choose_project_folder() == folder
