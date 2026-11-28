"""Native GUI fixture launch preflight without starting a real editor."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.gui import test_kicad_gui_live_context as gui
from tests.gui.test_native_ipc_discovery_recovery import _installed_bin_dir


def test_gui_launcher_forwards_isolated_environment(tmp_path: Path, monkeypatch) -> None:
    editor = tmp_path / "pcbnew.exe"
    board = tmp_path / "probe.kicad_pcb"
    env = {"KICAD_CONFIG_HOME": str(tmp_path / "private-profile")}
    process = MagicMock(pid=42)
    launch = MagicMock(return_value=process)
    monkeypatch.setattr(gui.subprocess, "Popen", launch)

    managed = gui._launch_process("private-pcb", editor, board, tmp_path / "logs", env=env)

    assert managed.process is process
    launch.assert_called_once_with(
        [str(editor), str(board)],
        cwd=board.parent,
        env=env,
        stdout=gui.subprocess.PIPE,
        stderr=gui.subprocess.PIPE,
        text=True,
    )
    assert (managed.log_dir / "private-pcb-pid.txt").read_text(encoding="utf-8") == "42"


def test_native_install_requires_absolute_local_directory(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="local KiCad"):
        _installed_bin_dir("relative/bin")
    with pytest.raises(AssertionError):
        _installed_bin_dir(str(tmp_path))
    (tmp_path / "pcbnew.exe").touch()
    (tmp_path / "kicad-cli.exe").touch()
    assert _installed_bin_dir(str(tmp_path)) == tmp_path.resolve()
