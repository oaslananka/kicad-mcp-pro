"""Compact read-only sidecar for KiCad 10's out-of-process IPC plugin API.

KiCad 10 cannot embed external IPC plugin windows as native docked panes.
This normal (not always-on-top) tool window stays independent of the editor.
"""

from __future__ import annotations

import sys
import threading
import webbrowser

try:
    import wx
except ImportError:
    print(
        "KiCad MCP Pro Companion requires KiCad's wxPython-enabled desktop runtime.",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

from companion_core import (
    BoardSummary,
    backend_status,
    board_summary,
    dashboard_url,
    repair_ipc_dependencies,
    sync_board_context,
)

BACKGROUND = "#111923"
SURFACE = "#1B2634"
FOREGROUND = "#F0F4FA"
SECONDARY = "#AFBECD"
ACCENT = "#9CC6FB"
CONNECTED = "#78DDB8"
WARNING = "#F0C980"
PRIMARY = "#3177BB"


def _text(
    parent: wx.Window,
    value: str,
    *,
    size: int = 10,
    color: str = FOREGROUND,
    bold: bool = False,
) -> wx.StaticText:
    label = wx.StaticText(parent, label=value)
    font = label.GetFont()
    font.SetPointSize(size)
    if bold:
        font.SetWeight(wx.FONTWEIGHT_BOLD)
    label.SetFont(font)
    label.SetForegroundColour(wx.Colour(color))
    return label


def _display_board_name(name: str, limit: int = 34) -> str:
    """Keep long real-world filenames readable without widening the sidecar."""
    if len(name) <= limit:
        return name
    left = (limit - 1) // 2
    return f"{name[:left]}…{name[-(limit - left - 1) :]}"


def _surface(parent: wx.Panel) -> tuple[wx.Panel, wx.BoxSizer]:
    surface = wx.Panel(parent)
    surface.SetBackgroundColour(wx.Colour(SURFACE))
    content = wx.BoxSizer(wx.VERTICAL)
    padding = wx.BoxSizer(wx.VERTICAL)
    padding.Add(content, 1, wx.EXPAND | wx.ALL, 12)
    surface.SetSizer(padding)
    return surface, content


class CompanionFrame(wx.Frame):
    """Non-modal, independent KiCad IPC companion; never mutates board data."""

    def __init__(self) -> None:
        super().__init__(
            None,
            title="MCP Pro — PCB Companion",
            size=(390, 565),
            style=wx.DEFAULT_FRAME_STYLE,
        )
        self.SetMinSize((350, 505))
        self.SetBackgroundColour(wx.Colour(BACKGROUND))
        self.board: BoardSummary | None = None
        self.last_synced_board: BoardSummary | None = None
        self.ready = False
        self._sync_busy = False

        panel = wx.Panel(self)
        panel.SetBackgroundColour(wx.Colour(BACKGROUND))
        layout = wx.BoxSizer(wx.VERTICAL)

        header = wx.BoxSizer(wx.HORIZONTAL)
        brand = wx.BoxSizer(wx.VERTICAL)
        brand.Add(_text(panel, "MCP Pro", size=17, bold=True), 0, wx.BOTTOM, 2)
        brand.Add(_text(panel, "KiCad PCB Companion", size=9, color=SECONDARY), 0)
        header.Add(brand, 1)
        self.connection_label = _text(panel, "● Checking", size=10, color=SECONDARY)
        header.Add(self.connection_label, 0, wx.TOP, 8)
        layout.Add(header, 0, wx.EXPAND | wx.BOTTOM, 20)

        board_panel, board_content = _surface(panel)
        board_content.Add(
            _text(board_panel, "Active board", size=10, color=ACCENT), 0, wx.BOTTOM, 7
        )
        self.board_label = _text(board_panel, "Connecting to KiCad…", size=12, bold=True)
        board_content.Add(self.board_label, 0, wx.BOTTOM, 7)
        self.board_details = _text(board_panel, "Board data unavailable", size=9, color=SECONDARY)
        board_content.Add(self.board_details, 0, wx.BOTTOM, 4)
        self.selection_label = _text(board_panel, "", size=9, color=SECONDARY)
        board_content.Add(self.selection_label, 0)
        layout.Add(board_panel, 0, wx.EXPAND | wx.BOTTOM, 12)

        self.selected_panel, selection_content = _surface(panel)
        selection_content.Add(
            _text(self.selected_panel, "Selected footprint", size=10, color=ACCENT),
            0,
            wx.BOTTOM,
            6,
        )
        self.value_label = _text(self.selected_panel, "", size=10, bold=True)
        selection_content.Add(self.value_label, 0, wx.BOTTOM, 4)
        self.footprint_label = _text(self.selected_panel, "", size=9, color=SECONDARY)
        selection_content.Add(self.footprint_label, 0, wx.BOTTOM, 4)
        self.net_label = _text(self.selected_panel, "", size=9, color=SECONDARY)
        selection_content.Add(self.net_label, 0)
        layout.Add(self.selected_panel, 0, wx.EXPAND | wx.BOTTOM, 12)
        self.selected_panel.Hide()

        service_header = wx.BoxSizer(wx.HORIZONTAL)
        service_header.Add(_text(panel, "Engineering service", size=10, bold=True), 1)
        layout.Add(service_header, 0, wx.EXPAND | wx.BOTTOM, 6)
        self.service_label = _text(
            panel, "Checking the local MCP backend…", size=9, color=SECONDARY
        )
        self.service_label.Wrap(320)
        layout.Add(self.service_label, 0, wx.EXPAND | wx.BOTTOM, 16)

        self.sync_btn = wx.Button(panel, label="Sync PCB context")
        self.sync_btn.SetMinSize((-1, 40))
        self.sync_btn.SetBackgroundColour(wx.Colour(PRIMARY))
        self.sync_btn.SetForegroundColour(wx.Colour(FOREGROUND))
        layout.Add(self.sync_btn, 0, wx.EXPAND | wx.BOTTOM, 10)

        self.feedback_label = _text(panel, "Ready to sync when you are.", size=9, color=SECONDARY)
        self.feedback_label.Wrap(320)
        layout.Add(self.feedback_label, 0, wx.EXPAND | wx.BOTTOM, 17)

        secondary = wx.BoxSizer(wx.HORIZONTAL)
        self.dashboard_btn = wx.Button(panel, label="Open dashboard")
        self.refresh_btn = wx.Button(panel, label="Refresh")
        secondary.Add(self.dashboard_btn, 1, wx.RIGHT, 8)
        secondary.Add(self.refresh_btn, 0)
        layout.Add(secondary, 0, wx.EXPAND | wx.BOTTOM, 9)

        self.repair_btn = wx.Button(panel, label="Repair KiCad IPC dependencies…")
        layout.Add(self.repair_btn, 0, wx.EXPAND | wx.BOTTOM, 8)
        self.repair_btn.Hide()

        layout.Add(
            _text(panel, "Read-only  ·  Nothing is changed on your PCB", size=9, color=SECONDARY),
            0,
            wx.TOP,
            7,
        )
        panel.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND | wx.ALL, 18)
        self.SetSizer(outer)

        self.dashboard_btn.Bind(wx.EVT_BUTTON, lambda _event: self.open_dashboard())
        self.refresh_btn.Bind(wx.EVT_BUTTON, lambda _event: self.refresh())
        self.sync_btn.Bind(wx.EVT_BUTTON, self.sync_context)
        self.repair_btn.Bind(wx.EVT_BUTTON, self.repair_dependencies)
        self.Bind(wx.EVT_ACTIVATE, self.on_activate)
        wx.CallAfter(self.refresh)

    def place_at_screen_edge(self) -> None:
        """Place on the current display edge without owning or resizing KiCad.

        This is sidecar positioning, NOT a native dock, and uses only wx APIs.
        Moving KiCad later does not move the independent Companion window.
        """
        if not hasattr(wx, "Display") or not hasattr(wx, "GetMousePosition"):
            self.Centre()
            return
        screen = wx.Display.GetFromPoint(wx.GetMousePosition())
        if screen == wx.NOT_FOUND:
            self.Centre()
            return
        bounds = wx.Display(screen).GetClientArea()
        size = self.GetSize()
        if bounds.GetWidth() < size.GetWidth() + 40:
            self.Centre()
            return
        x = bounds.GetRight() - size.GetWidth() - 12
        y = bounds.GetTop() + 70
        self.SetPosition((x, y))

    def _display_board(self, summary: BoardSummary) -> None:
        self.board = summary
        self.repair_btn.Hide()
        self.board_label.SetLabel(_display_board_name(summary.name or "Untitled PCB"))
        self.board_label.SetToolTip(summary.name or "Untitled PCB")
        self.board_details.SetLabel(
            f"{summary.footprints} footprints   ·   {summary.nets} nets   ·   "
            f"{summary.selected} selected"
        )
        self.selection_label.SetLabel(
            f"Selected: {summary.selected_reference}" if summary.selected_reference else ""
        )
        self.board_label.SetForegroundColour(wx.Colour(FOREGROUND))
        self._display_selection(summary)

    def _display_selection(self, summary: BoardSummary) -> None:
        """Only show concrete single-footprint data; never infer DRC or pad health."""
        if summary.selected != 1 or summary.selected_pad_count is None:
            self.selected_panel.Hide()
            return
        self.value_label.SetLabel(
            f"Value: {summary.selected_value or '—'}  ·  {summary.selected_pad_count} pads"
        )
        self.footprint_label.SetLabel(
            _display_board_name(summary.selected_footprint or "Unknown footprint", 42)
        )
        self.footprint_label.SetToolTip(summary.selected_footprint)
        nets = ", ".join(summary.selected_nets[:2]) or "None"
        if len(summary.selected_nets) > 2:
            nets += f" +{len(summary.selected_nets) - 2} more"
        unassigned = summary.selected_unconnected_pads
        extra = (
            f"  ·  {unassigned} unassigned pad{'s' if unassigned != 1 else ''}"
            if unassigned
            else ""
        )
        self.net_label.SetLabel(_display_board_name(f"Nets: {nets}{extra}", 47))
        self.selected_panel.Show()

    def refresh_board(self) -> None:
        """Re-read PCB/selection on focus, without a potentially slow HTTP health check."""
        if self._sync_busy:
            return
        try:
            summary = board_summary()
        except ModuleNotFoundError as exc:
            self.board = None
            self.selected_panel.Hide()
            self.board_label.SetLabel("KiCad IPC needs setup")
            self.board_details.SetLabel(f"Missing Python module: {exc.name or 'unknown'}")
            self.selection_label.SetLabel("Choose Repair below to restore board access.")
            self.repair_btn.Show()
            self.board_label.SetForegroundColour(wx.Colour(WARNING))
        except Exception:
            self.board = None
            self.selected_panel.Hide()
            self.repair_btn.Hide()
            self.board_label.SetLabel("No active PCB")
            self.board_details.SetLabel("Open a saved board and enable KiCad's IPC API.")
            self.selection_label.SetLabel("")
            self.board_label.SetForegroundColour(wx.Colour(SECONDARY))
        else:
            self._display_board(summary)
            if self.last_synced_board is not None and summary != self.last_synced_board:
                self.feedback_label.SetLabel("PCB context changed. Sync to update MCP.")
                self.feedback_label.SetForegroundColour(wx.Colour(WARNING))

        self._update_connection_indicator()
        self.Layout()

    def _update_connection_indicator(self) -> None:
        online = self.ready and self.board is not None
        self.connection_label.SetLabel("● Connected" if online else "● Attention")
        self.connection_label.SetForegroundColour(wx.Colour(CONNECTED if online else WARNING))
        self.sync_btn.Enable(online and not self._sync_busy)

    def on_activate(self, event: wx.ActivateEvent) -> None:
        """Catch selections changed while the designer was working in PCB Editor."""
        if event.GetActive() and not self._sync_busy:
            self.refresh_board()
        event.Skip()

    def refresh(self) -> None:
        self.refresh_board()
        self.ready, status = backend_status()
        self.service_label.SetLabel(status)
        self.service_label.Wrap(330)
        online = self.ready and self.board is not None
        if self.last_synced_board is None or self.board == self.last_synced_board:
            self.feedback_label.SetLabel(
                "Ready to sync when you are."
                if online
                else "Open a board and check the connection."
            )
            self.feedback_label.SetForegroundColour(wx.Colour(SECONDARY))
        self._update_connection_indicator()
        self.service_label.SetForegroundColour(wx.Colour(SECONDARY))
        self.dashboard_btn.Enable(self.ready)
        self.Layout()

    def open_dashboard(self) -> None:
        if not self.ready:
            return
        try:
            url = dashboard_url()
        except ValueError:
            self.feedback_label.SetLabel("Dashboard URL must use loopback.")
            return
        webbrowser.open(url)

    def repair_dependencies(self, _event: wx.CommandEvent) -> None:
        confirmation = wx.MessageBox(
            "Download and install missing Python packages into KiCad's private "
            "plugin environment? This does not change system Python. "
            "An internet connection may be required.",
            "Repair KiCad MCP Pro IPC dependencies",
            wx.YES_NO | wx.ICON_QUESTION,
        )
        if confirmation != wx.YES:
            return
        self.repair_btn.Enable(False)
        self.feedback_label.SetLabel("Repairing KiCad IPC dependencies…")

        def worker() -> None:
            try:
                repair_ipc_dependencies()
            except RuntimeError:
                wx.CallAfter(
                    self._repair_done, "Repair failed; check network access and plugin logs.", False
                )
            else:
                wx.CallAfter(self._repair_done, "Dependencies installed.", True)

        threading.Thread(target=worker, daemon=True, name="kicad-mcp-ipc-repair").start()

    def _repair_done(self, message: str, success: bool) -> None:
        self.repair_btn.Enable(True)
        self.feedback_label.SetLabel(message)
        if success:
            self.refresh()

    def sync_context(self, _event: wx.CommandEvent) -> None:
        if not self.ready or self.board is None or self._sync_busy:
            return
        self._sync_busy = True
        self.sync_btn.Enable(False)
        self.feedback_label.SetLabel("Reading the current PCB selection…")
        self.feedback_label.SetForegroundColour(wx.Colour(SECONDARY))

        def worker() -> None:
            try:
                # Never sync a snapshot captured when the window first opened.
                # Users can change the board or selection while editing KiCad.
                snapshot = board_summary()
            except Exception:
                wx.CallAfter(
                    self._sync_done, "Unable to read current PCB. Nothing sent.", False, None
                )
                return
            try:
                sync_board_context(snapshot)
            except Exception:
                wx.CallAfter(
                    self._sync_done, "Context sync failed; check backend access.", False, snapshot
                )
            else:
                wx.CallAfter(self._sync_done, "PCB context synced.", True, snapshot)

        threading.Thread(target=worker, daemon=True, name="kicad-mcp-context-sync").start()

    def _sync_done(self, message: str, success: bool, snapshot: BoardSummary | None) -> None:
        self._sync_busy = False
        if snapshot is not None:
            self._display_board(snapshot)
        else:
            self.board = None
            self.selected_panel.Hide()
            self.board_label.SetLabel("No active PCB")
            self.board_details.SetLabel("Open a saved PCB and refresh to retry.")
            self.selection_label.SetLabel("")
        if success:
            self.last_synced_board = snapshot
        self.feedback_label.SetLabel(message)
        self.feedback_label.SetForegroundColour(wx.Colour(CONNECTED if success else WARNING))
        self._update_connection_indicator()
        self.Layout()


def main() -> int:
    app = wx.App(redirect=False)
    frame = CompanionFrame()
    frame.Show()
    frame.place_at_screen_edge()
    app.MainLoop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
