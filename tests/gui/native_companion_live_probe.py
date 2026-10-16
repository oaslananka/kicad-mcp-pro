"""Mac GUI/IPC probe executed in the KiCad-managed Companion Python environment.

Invoked only by the opt-in signed-KiCad qualification workflow, not normal CI.
Only an isolated fixture is read; this script does not mutate a PCB.
"""

from __future__ import annotations

import sys
from pathlib import Path

import wx


def main() -> int:
    plugin = Path(sys.argv[1]).resolve()
    expected_board = sys.argv[2]
    sys.path.insert(0, str(plugin))

    from companion import CompanionFrame

    app = wx.App(False)
    frame = CompanionFrame()
    frame.Show()
    outcome = {"ok": False}

    def verify() -> None:
        try:
            frame.refresh()
            board = frame.board
            outcome["ok"] = bool(
                board is not None
                and board.name == expected_board
                and board.footprints > 0
                and board.nets > 0
                and not frame.sync_btn.IsEnabled()
            )
        except Exception:
            outcome["ok"] = False
        finally:
            frame.Close()

    wx.CallLater(2500, verify)
    app.MainLoop()
    print("MACOS_COMPANION_LIVE_PASS" if outcome["ok"] else "MACOS_COMPANION_LIVE_FAIL", flush=True)
    return 0 if outcome["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
