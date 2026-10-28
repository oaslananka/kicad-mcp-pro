"""Fail-closed tests for optional manual X11 KiCad editor tiling."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "packages" / "kicad-plugin"
sys.path.insert(0, str(PLUGIN))
import companion_tiling as tile  # noqa: E402


def test_layout_leaves_a_full_editor_viewport() -> None:
    editor, companion = tile._layout((66, 32, 1919, 1079), 330)
    assert editor == (74, 39, 1489, 957)
    assert companion == (1577, 102)
    assert editor[0] + editor[2] + 14 == companion[0]
    with pytest.raises(RuntimeError, match="too small"):
        tile._layout((0, 0, 800, 600), 330)
    with pytest.raises(RuntimeError, match="too small"):
        tile._layout((0, 0, 1919, 1079), 600)


def test_tiling_respects_explicit_platform_and_display_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tile.sys, "platform", "win32")
    with pytest.raises(RuntimeError, match="Linux"):
        tile.tile_editor("board.kicad_pcb", (0, 0, 1919, 1079), 330)
    monkeypatch.setattr(tile.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    with pytest.raises(RuntimeError, match="Linux"):
        tile.tile_editor("board.kicad_pcb", (0, 0, 1919, 1079), 330)


def test_editor_identity_requires_one_same_user_matching_pcb(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    windows = (101, 102, 103)
    probe = tile._X11.__new__(tile._X11)
    probe.root = 1
    monkeypatch.setattr(
        probe,
        "property",
        lambda window, name: (
            (32, windows)
            if (window, name) == (1, "_NET_CLIENT_LIST")
            else (8, b"board \xe2\x80\x94 PCB Editor")
            if name == "_NET_WM_NAME"
            else (32, (os.getpid(),))
        ),
    )
    monkeypatch.setattr(
        probe, "window_class", lambda window: "pcbnew" if window in (101, 102) else "other"
    )
    with pytest.raises(RuntimeError, match="one verified"):
        probe.editor("board.kicad_pcb")
    monkeypatch.setattr(
        probe, "window_class", lambda window: "pcbnew" if window == 101 else "other"
    )
    assert probe.editor("board.kicad_pcb") == 101
    with pytest.raises(RuntimeError, match="one verified"):
        probe.editor("different.kicad_pcb")


def test_tile_restores_maximize_if_window_manager_ignores_geometry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tile.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tile.time, "sleep", lambda _: None)
    window = Mock()
    window.editor.return_value = 7
    window.geometry.return_value = (66, 69, 1854, 1011)
    window.maximized.return_value = True
    window.__enter__ = Mock(return_value=window)
    window.__exit__ = Mock(return_value=None)
    monkeypatch.setattr(tile, "_X11", lambda: window)
    with pytest.raises(RuntimeError, match="did not honor"):
        tile.tile_editor("board.kicad_pcb", (66, 32, 1919, 1079), 330)
    assert window.set_maximized.call_count == 2
    window.set_maximized.assert_any_call(7, False)
    window.set_maximized.assert_any_call(7, True)


def test_unmaximized_editor_is_not_rearranged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tile.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    window = Mock()
    window.__enter__ = Mock(return_value=window)
    window.__exit__ = Mock(return_value=None)
    window.editor.return_value = 7
    window.geometry.return_value = (66, 69, 1200, 900)
    window.maximized.return_value = False
    monkeypatch.setattr(tile, "_X11", lambda: window)
    with pytest.raises(RuntimeError, match="Maximize KiCad first"):
        tile.tile_editor("board.kicad_pcb", (66, 32, 1919, 1079), 330)
    window.move_resize.assert_not_called()
    window.set_maximized.assert_not_called()


def test_tile_and_restore_verified_same_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tile.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(tile.time, "sleep", lambda _: None)
    old = (66, 69, 1854, 1011)
    new = (74, 39, 1489, 957)
    state = {"max": True, "geom": old, "id": 7}

    class FakeX11:
        def __enter__(self) -> FakeX11:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def editor(self, _board):
            return state["id"]

        def maximized(self, _id):
            return state["max"]

        def geometry(self, _id):
            return state["geom"]

        def set_maximized(self, _id, value):
            state["max"] = value

        def move_resize(self, _id, geom):
            state["geom"] = geom

    monkeypatch.setattr(tile, "_X11", FakeX11)
    result = tile.tile_editor("board.kicad_pcb", (66, 32, 1919, 1079), 330)
    assert result.original == tile.EditorPlacement(7, old, True, "board.kicad_pcb")
    assert state == {"max": False, "geom": new, "id": 7}
    state["id"] = 9
    with pytest.raises(RuntimeError, match="changed"):
        tile.restore_editor(result.original)
    assert state["max"] is False
    state["id"] = 7
    tile.restore_editor(result.original)
    assert state["max"] is True
