"""Headless wx interaction contracts for the KiCad IPC Companion.

wxPython is supplied by KiCad's runtime. CI does not have to install a desktop
environment or mutate KiCad: these tests exercise GUI actions with wx fakes.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLUGIN = ROOT / "packages" / "kicad-plugin"


@pytest.fixture
def ui(monkeypatch: pytest.MonkeyPatch) -> tuple[types.ModuleType, types.ModuleType]:
    class FakeFrame:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.calls = Mock()

        def __getattr__(self, name: str) -> Mock:
            return getattr(self.calls, name)

    wx = types.ModuleType("wx")
    wx.Frame = FakeFrame
    wx.Panel = Mock(side_effect=lambda *a, **k: Mock())
    wx.BoxSizer = Mock(side_effect=lambda *a, **k: Mock())
    wx.StaticText = Mock(side_effect=lambda *a, **k: Mock())
    wx.Button = Mock(side_effect=lambda *a, **k: Mock())
    wx.Colour = lambda value: value
    wx.App = Mock()
    wx.CallAfter = lambda callback, *args: callback(*args)
    wx.MessageBox = Mock()
    for name in ("VERTICAL", "HORIZONTAL", "EXPAND", "BOTTOM", "ALL", "TOP", "RIGHT"):
        setattr(wx, name, 0)
    wx.DEFAULT_FRAME_STYLE = 0
    wx.FONTWEIGHT_BOLD = 700
    wx.EVT_BUTTON = 100
    wx.EVT_ACTIVATE = 101
    wx.YES = 1
    wx.NO = 0
    wx.YES_NO = 2
    wx.ICON_QUESTION = 4
    wx.MessageBox.return_value = wx.NO

    monkeypatch.syspath_prepend(str(PLUGIN))
    monkeypatch.setitem(sys.modules, "wx", wx)
    spec = importlib.util.spec_from_file_location(
        "_test_native_companion_window", PLUGIN / "companion.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, wx


def _ready(ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch):
    module, _wx = ui
    monkeypatch.setattr(
        module,
        "board_summary",
        lambda: module.BoardSummary("test.kicad_pcb", "test", 7, 11, 2),
    )
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    return module.CompanionFrame()


def test_window_shows_board_and_enables_read_only_actions(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = _ready(ui, monkeypatch)
    assert frame.board is not None
    assert frame.board.footprints == 7
    assert frame.ready
    frame.board_label.SetLabel.assert_called_with("test.kicad_pcb")
    frame.board_details.SetLabel.assert_called_with("7 footprints   ·   11 nets   ·   2 selected")
    frame.connection_label.SetLabel.assert_called_with("● Connected")
    frame.dashboard_btn.Enable.assert_called_with(True)
    frame.sync_btn.Enable.assert_called_with(True)
    frame.repair_btn.Hide.assert_called()


def test_missing_board_disables_context_sync(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui

    def offline() -> object:
        raise OSError("Board is closed")

    monkeypatch.setattr(module, "board_summary", offline)
    monkeypatch.setattr(module, "backend_status", lambda: (False, "Not connected"))
    frame = module.CompanionFrame()
    assert frame.board is None
    assert not frame.ready
    frame.board_label.SetLabel.assert_called_with("No active PCB")
    frame.connection_label.SetLabel.assert_called_with("● Attention")
    frame.dashboard_btn.Enable.assert_called_with(False)
    frame.sync_btn.Enable.assert_called_with(False)


def test_missing_ipc_dependency_offers_repair(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui

    def missing() -> object:
        raise ModuleNotFoundError("Missing dependency", name="google")

    monkeypatch.setattr(module, "board_summary", missing)
    monkeypatch.setattr(module, "backend_status", lambda: (False, "Not connected"))
    frame = module.CompanionFrame()
    frame.board_label.SetLabel.assert_called_with("KiCad IPC needs setup")
    frame.board_details.SetLabel.assert_called_with("Missing Python module: google")
    frame.repair_btn.Show.assert_called()


def test_dashboard_action_uses_loopback_only(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    browser = Mock()
    urls = Mock(side_effect=lambda part="": "http://127.0.0.1:3334/ui" + part)
    monkeypatch.setattr(module.webbrowser, "open", browser)
    monkeypatch.setattr(module, "dashboard_url", urls)
    frame.open_dashboard()
    browser.assert_called_once_with("http://127.0.0.1:3334/ui")


def test_unsafe_dashboard_url_never_opens_browser(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    monkeypatch.setattr(module, "dashboard_url", Mock(side_effect=ValueError("Not loopback")))
    browser = Mock()
    monkeypatch.setattr(module.webbrowser, "open", browser)
    frame.open_dashboard()
    browser.assert_not_called()
    frame.feedback_label.SetLabel.assert_called_with("Dashboard URL must use loopback.")


def test_context_sync_success_and_failure(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)

    class ImmediateThread:
        def __init__(self, *, target: Callable[[], None], **_kwargs: object) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    monkeypatch.setattr(module, "threading", types.SimpleNamespace(Thread=ImmediateThread))
    sync = Mock()
    monkeypatch.setattr(module, "sync_board_context", sync)
    frame.sync_context(None)
    sync.assert_called_once_with(frame.board)
    frame.feedback_label.SetLabel.assert_called_with("PCB context synced.")

    sync.side_effect = OSError("backend disconnected")
    frame.sync_context(None)
    frame.feedback_label.SetLabel.assert_called_with("Context sync failed; check backend access.")


def test_sync_reads_latest_selection_not_cached_board(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    stale = frame.board
    current = module.BoardSummary("new-board.kicad_pcb", "new-board", 3, 4, 1, "", "U7")
    monkeypatch.setattr(module, "board_summary", lambda: current)
    monkeypatch.setattr(
        module, "threading", types.SimpleNamespace(Thread=lambda **k: Mock(start=k["target"]))
    )
    sync = Mock()
    monkeypatch.setattr(module, "sync_board_context", sync)
    frame.sync_context(None)
    assert frame.board == current
    assert frame.last_synced_board == current
    assert frame.board != stale
    sync.assert_called_once_with(current)
    frame.selection_label.SetLabel.assert_called_with("Selected: U7")
    frame.feedback_label.SetLabel.assert_called_with("PCB context synced.")


def test_sync_read_failure_never_calls_server(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    monkeypatch.setattr(module, "board_summary", Mock(side_effect=OSError("IPC closed")))
    monkeypatch.setattr(
        module, "threading", types.SimpleNamespace(Thread=lambda **k: Mock(start=k["target"]))
    )
    sync = Mock()
    monkeypatch.setattr(module, "sync_board_context", sync)
    frame.sync_context(None)
    sync.assert_not_called()
    assert frame.board is None
    frame.sync_btn.Enable.assert_called_with(False)
    frame.feedback_label.SetLabel.assert_called_with("Unable to read current PCB. Nothing sent.")


def test_regaining_focus_refreshes_selected_reference_without_backend_request(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, wx = ui
    frame = _ready(ui, monkeypatch)
    frame.last_synced_board = frame.board
    fresh = module.BoardSummary("test.kicad_pcb", "test", 7, 11, 1, "", "R4")
    read = Mock(return_value=fresh)
    status = Mock(return_value=(True, "Connected"))
    monkeypatch.setattr(module, "board_summary", read)
    monkeypatch.setattr(module, "backend_status", status)
    event = Mock()
    event.GetActive.return_value = True
    frame.on_activate(event)
    read.assert_called_once_with()
    status.assert_not_called()
    frame.selection_label.SetLabel.assert_called_with("Selected: R4")
    frame.feedback_label.SetLabel.assert_called_with("PCB context changed. Sync to update MCP.")
    event.Skip.assert_called_once_with()
    assert wx.EVT_ACTIVATE == 101


def test_repair_requires_confirmation_and_reports_completion(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, wx = ui
    frame = _ready(ui, monkeypatch)

    class ImmediateThread:
        def __init__(self, *, target: Callable[[], None], **_kwargs: object) -> None:
            self.target = target

        def start(self) -> None:
            self.target()

    monkeypatch.setattr(module, "threading", types.SimpleNamespace(Thread=ImmediateThread))
    repair = Mock()
    monkeypatch.setattr(module, "repair_ipc_dependencies", repair)
    frame.repair_dependencies(None)
    repair.assert_not_called()

    wx.MessageBox.return_value = wx.YES
    frame.repair_dependencies(None)
    repair.assert_called_once_with()

    repair.side_effect = RuntimeError("No connection")
    frame.repair_dependencies(None)
    frame.feedback_label.SetLabel.assert_called_with(
        "Repair failed; check network access and plugin logs."
    )


def test_selected_footprint_card_shows_read_only_engineering_details(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    current = module.BoardSummary(
        "board.kicad_pcb",
        "demo",
        3,
        2,
        1,
        "",
        "R1",
        "1k",
        "Resistor_SMD:R_0603_1608Metric",
        2,
        ("LED_A",),
        1,
    )
    monkeypatch.setattr(module, "board_summary", lambda: current)
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    frame = module.CompanionFrame()
    frame.selected_panel.Show.assert_called()
    frame.value_label.SetLabel.assert_called_with("Value: 1k  ·  2 pads")
    frame.footprint_label.SetLabel.assert_called_with("Resistor_SMD:R_0603_1608Metric")
    frame.net_label.SetLabel.assert_called_with("Nets: LED_A  ·  1 unassigned pad")


def test_same_net_peers_are_inspected_without_claiming_copper_connection(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    current = module.BoardSummary(
        "board.kicad_pcb",
        "demo",
        3,
        2,
        1,
        "",
        "R1",
        "1k",
        "Resistor:0603",
        2,
        ("LED_A",),
        1,
        (("LED_A", ("LED1",)),),
    )
    monkeypatch.setattr(module, "board_summary", lambda: current)
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    frame = module.CompanionFrame()
    frame.peer_label.SetLabel.assert_called_with("Also assigned: LED_A: LED1")
    assert "do not prove routed copper" in frame.peer_label.SetToolTip.call_args.args[0]


def test_no_shared_net_does_not_invent_neighbours(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    current = module.BoardSummary(
        "board.kicad_pcb",
        "demo",
        2,
        1,
        1,
        "",
        "R1",
        "1k",
        "Resistor:0603",
        2,
        ("LED_A",),
        1,
    )
    monkeypatch.setattr(module, "board_summary", lambda: current)
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    frame = module.CompanionFrame()
    frame.peer_label.SetLabel.assert_called_with("No other footprints share these net labels")


def test_selected_footprint_card_hidden_after_selection_cleared(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    selected = module.BoardSummary(
        "board.kicad_pcb", "demo", 3, 2, 1, "", "C1", "100n", "Cap:0603", 2
    )
    read = Mock(side_effect=[selected, module.BoardSummary("board.kicad_pcb", "demo", 3, 2, 0)])
    monkeypatch.setattr(module, "board_summary", read)
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    frame = module.CompanionFrame()
    frame.selected_panel.Show.assert_called_once()
    frame.refresh_board()
    frame.selected_panel.Hide.assert_called()
    frame.selection_label.SetLabel.assert_called_with("")


def test_saved_drc_is_opt_in_and_displays_saved_only_report(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    run = Mock(return_value=module.SavedDrcResult(14, 3, 4, 0, "10.0.7"))
    monkeypatch.setattr(module, "run_saved_board_drc", run)
    monkeypatch.setattr(
        module, "threading", types.SimpleNamespace(Thread=lambda **kw: Mock(start=kw["target"]))
    )
    run.assert_not_called()
    frame.check_saved_drc(None)
    run.assert_called_once_with(frame.board)
    frame.drc_label.SetLabel.assert_called_with("Saved PCB: 14 errors · 3 warnings · 4 unconnected")
    assert "unsaved KiCad edits" in frame.drc_label.SetToolTip.call_args.args[0]
    frame.drc_btn.Enable.assert_called_with(True)


def test_drc_findings_open_read_only_modal_and_clear_on_failure(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, wx = ui
    frame = _ready(ui, monkeypatch)
    finding = module.DrcFinding(
        "error",
        "shorting_items",
        "Different nets shorted",
        ("Pad 2 [GND] of R1",),
        (11.5, 9.25),
    )
    result = module.SavedDrcResult(1, 0, 0, 0, "10.0.7", (finding,), "mm")
    frame._drc_done(result, (frame.board.name, frame.board.project_path))
    frame.findings_btn.SetLabel.assert_called_with("View 1 DRC findings")
    frame.findings_btn.Show.assert_called_once_with()
    wx.Dialog = Mock(return_value=Mock())
    wx.ListCtrl = Mock(return_value=Mock())
    wx.TextCtrl = Mock(return_value=Mock())
    wx.LC_REPORT = 1
    wx.LC_SINGLE_SEL = 2
    wx.TE_MULTILINE = 4
    wx.TE_READONLY = 8
    wx.TE_WORDWRAP = 16
    wx.EVT_LIST_ITEM_SELECTED = 102
    wx.ALIGN_RIGHT = 32
    wx.ID_OK = 1
    frame.show_drc_findings(None)
    wx.ListCtrl.assert_called_once()
    assert any(
        call.args[1:] == (1, "Shorting items")
        for call in wx.ListCtrl.return_value.SetItem.call_args_list
    )
    wx.TextCtrl.assert_called_once()
    assert wx.TextCtrl.call_args.kwargs["style"] & wx.TE_READONLY
    assert "Pad 2 [GND] of R1" in wx.TextCtrl.call_args.kwargs["value"]
    assert "11.500, 9.250 mm" in wx.TextCtrl.call_args.kwargs["value"]
    wx.Dialog.return_value.ShowModal.assert_called_once_with()
    wx.Dialog.return_value.Destroy.assert_called_once_with()
    frame._drc_done(None, None)
    frame.findings_btn.Hide.assert_called()
    frame.show_drc_findings(None)
    assert wx.Dialog.call_count == 1


def test_saved_drc_failure_never_displays_false_success(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    monkeypatch.setattr(module, "run_saved_board_drc", Mock(side_effect=RuntimeError("failure")))
    monkeypatch.setattr(
        module, "threading", types.SimpleNamespace(Thread=lambda **kw: Mock(start=kw["target"]))
    )
    frame.check_saved_drc(None)
    frame.drc_label.SetLabel.assert_called_with("DRC unavailable · saved file not checked")


def test_drc_snapshot_cleared_when_active_board_disappears(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    frame = _ready(ui, monkeypatch)
    result = module.SavedDrcResult(
        1, 0, 0, 0, "10.0.7", (module.DrcFinding("error", "shorting_items", "short"),)
    )
    frame._drc_done(result, (frame.board.name, frame.board.project_path))
    monkeypatch.setattr(module, "board_summary", Mock(side_effect=OSError("board closed")))
    frame.refresh_board()
    assert frame._drc_result is None
    frame.findings_btn.Hide.assert_called()
    frame.drc_label.SetLabel.assert_called_with("DRC snapshot unavailable · no active board")


def test_saved_drc_disables_itself_when_no_board(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    monkeypatch.setattr(module, "board_summary", Mock(side_effect=OSError("closed")))
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Ready"))
    frame = module.CompanionFrame()
    run = Mock()
    monkeypatch.setattr(module, "run_saved_board_drc", run)
    frame.check_saved_drc(None)
    run.assert_not_called()
    frame.drc_btn.Enable.assert_called_with(False)


def test_long_board_filenames_are_shortened_without_losing_tooltip(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    name = "rev-long-product-hardware-validation-fixture_very-long.kicad_pcb"
    monkeypatch.setattr(
        module, "board_summary", lambda: module.BoardSummary(name, "fixture", 3, 2, 0)
    )
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Connected"))
    frame = module.CompanionFrame()
    display = module._display_board_name(name)
    assert len(display) == 34
    assert display.endswith(".kicad_pcb")
    assert "…" in display
    frame.board_label.SetLabel.assert_called_with(display)
    frame.board_label.SetToolTip.assert_called_with(name)


def test_selection_reference_is_visible_when_available(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, _wx = ui
    monkeypatch.setattr(
        module,
        "board_summary",
        lambda: module.BoardSummary("board.kicad_pcb", "board", 4, 3, 1, "", "U3"),
    )
    monkeypatch.setattr(module, "backend_status", lambda: (True, "Backend ready"))
    frame = module.CompanionFrame()
    frame.selection_label.SetLabel.assert_called_with("Selected: U3")


def test_sidecar_has_no_always_on_top_flag(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    frame = _ready(ui, monkeypatch)
    frame.place_at_screen_edge()
    # Fake wx does not expose monitor geometry; placement safely falls back
    # rather than affecting a KiCad editor window.
    frame.calls.Centre.assert_called_once()


def test_sidecar_positions_on_active_display_without_resizing_editor(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, wx = ui
    frame = _ready(ui, monkeypatch)

    class Bounds:
        def GetWidth(self) -> int:  # noqa: N802
            return 1920

        def GetRight(self) -> int:  # noqa: N802
            return 1919

        def GetTop(self) -> int:  # noqa: N802
            return 0

    class Display:
        @staticmethod
        def GetFromPoint(_point: object) -> int:  # noqa: N802
            return 0

        def __init__(self, _index: int) -> None:
            pass

        def GetClientArea(self) -> Bounds:  # noqa: N802
            return Bounds()

    wx.Display = Display
    wx.NOT_FOUND = -1
    wx.GetMousePosition = lambda: (1000, 250)
    frame.calls.GetSize.return_value.GetWidth.return_value = 390
    frame.place_at_screen_edge()
    frame.calls.SetPosition.assert_called_once_with((1517, 70))


def test_entrypoint_runs_wx_mainloop(
    ui: tuple[types.ModuleType, types.ModuleType], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, wx = ui
    monkeypatch.setattr(module, "board_summary", lambda: module.BoardSummary("", "", 0, 0, 0))
    monkeypatch.setattr(module, "backend_status", lambda: (False, "No backend"))
    assert module.main() == 0
    wx.App.assert_called_once_with(redirect=False)
    wx.App.return_value.MainLoop.assert_called_once_with()
