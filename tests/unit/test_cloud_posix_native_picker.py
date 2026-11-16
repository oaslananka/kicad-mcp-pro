"""Native POSIX folder chooser contract; tests never open any real UI."""

import asyncio
from pathlib import Path

import pytest

from kicad_mcp import cloud_posix_native_picker as picker


class FakeProcess:
    def __init__(self, status: int, stdout: str, stderr: str) -> None:
        self.returncode = status
        self.stdout = stdout.encode("utf-8")
        self.stderr = stderr.encode("utf-8")

    async def communicate(self) -> tuple[bytes, bytes]:
        return self.stdout, self.stderr


def stub_native_exec(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    stdout: str,
    stderr: str = "",
) -> list[tuple[tuple[str, ...], dict[str, object]]]:
    launched: list[tuple[tuple[str, ...], dict[str, object]]] = []

    async def launch(*args: str, **kwargs: object) -> FakeProcess:
        launched.append((args, kwargs))
        return FakeProcess(status, stdout, stderr)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    return launched


def test_linux_zenity_uses_argv_and_keeps_paths_local(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "KiCad Board"
    directory.mkdir()
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(
        picker.shutil,
        "which",
        lambda name: "/usr/bin/zenity" if name == "zenity" else None,
    )
    launched = stub_native_exec(monkeypatch, 0, str(directory) + "\n")

    assert picker.choose_project_folder() == directory
    argv, kwargs = launched[0]
    assert argv == (
        "zenity",
        "--file-selection",
        "--directory",
        "--title=Choose your local KiCad project folder",
    )
    assert kwargs == {
        "stdin": asyncio.subprocess.DEVNULL,
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
    }


def test_macos_osascript_cancellation_is_not_a_new_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/osascript")
    stub_native_exec(monkeypatch, 1, "", "execution error: User canceled. (-128)")
    assert picker.choose_project_folder() is None


def test_headless_linux_does_not_launch_any_picker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)

    async def no_launch(*_args: object, **_kwargs: object) -> FakeProcess:
        pytest.fail("No GUI process should be launched")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", no_launch)
    assert picker.native_picker_available() is False
    with pytest.raises(OSError, match="graphical"):
        picker.choose_project_folder()


def test_macos_non_cancel_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda name: "/usr/bin/osascript")
    stub_native_exec(monkeypatch, 1, "", "execution error: Permission denied. (-1743)")
    with pytest.raises(OSError, match="folder chooser"):
        picker.choose_project_folder()


def test_linux_zenity_owner_cancel_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/zenity")
    stub_native_exec(monkeypatch, 1, "")
    assert picker.choose_project_folder() is None


def test_macos_returns_owner_selected_local_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    folder = tmp_path / "KiCad Board"
    folder.mkdir()
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/osascript")
    launched = stub_native_exec(monkeypatch, 0, str(folder) + "\n")
    assert picker.choose_project_folder() == folder
    assert launched[0][0] == (
        "/usr/bin/osascript",
        "-e",
        'POSIX path of (choose folder with prompt "Choose your local KiCad project folder")',
    )


def test_launch_error_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/osascript")

    async def launch(*_args: object, **_kwargs: object) -> FakeProcess:
        raise OSError("simulated missing binary")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with pytest.raises(OSError, match="could not start"):
        picker.choose_project_folder()


def test_timeout_terminates_dialog_and_denies_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(picker.sys, "platform", "darwin")
    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/osascript")
    monkeypatch.setattr(picker, "_TIMEOUT", 0.01)
    processes: list[object] = []

    class HungDialog:
        returncode = -9
        killed = False

        async def communicate(self) -> tuple[bytes, bytes]:
            if not self.killed:
                await asyncio.sleep(60)
            return b"", b""

        def kill(self) -> None:
            self.killed = True

    async def launch(*_args: object, **_kwargs: object) -> HungDialog:
        process = HungDialog()
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", launch)
    with pytest.raises(OSError, match="timed out"):
        picker.choose_project_folder()
    assert len(processes) == 1
    assert isinstance(processes[0], HungDialog) and processes[0].killed


def test_native_dialog_exec_never_invokes_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    directory = tmp_path / "selected"
    directory.mkdir()
    monkeypatch.setattr(picker.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    monkeypatch.setattr(picker.shutil, "which", lambda _name: "/usr/bin/zenity")
    launched = stub_native_exec(monkeypatch, 0, str(directory) + "\n")
    assert picker.choose_project_folder() == directory
    assert "shell" not in launched[0][1]
