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
    outcome = {
        "ok": False,
        "board": False,
        "name": False,
        "footprints": False,
        "nets": False,
        "syncDisabled": False,
        "error": "none",
        "stage": "init",
    }

    def verify() -> None:
        try:
            outcome["stage"] = "refresh"
            frame.refresh()
            outcome["stage"] = "board"
            board = frame.board
            outcome["board"] = board is not None
            outcome["name"] = bool(board is not None and board.name == expected_board)
            outcome["footprints"] = bool(board is not None and board.footprints > 0)
            outcome["nets"] = bool(board is not None and board.nets > 0)
            outcome["stage"] = "widget"
            outcome["syncDisabled"] = not frame.sync_btn.IsEnabled()
            outcome["ok"] = all(
                outcome[key] for key in ("board", "name", "footprints", "nets", "syncDisabled")
            )
        except Exception as exc:
            exception_name = type(exc).__name__
            known_errors = {
                "AttributeError",
                "RuntimeError",
                "TypeError",
                "ValueError",
                "ImportError",
                "ModuleNotFoundError",
                "OSError",
                "KeyError",
                "wxAssertionError",
                "PyDeadObjectError",
                "FileNotFoundError",
                "ConnectionError",
                "TimeoutError",
                "AssertionError",
            }
            outcome["error"] = exception_name if exception_name in known_errors else "Other"
        finally:
            frame.Close()

    wx.CallLater(2500, verify)
    app.MainLoop()
    if not outcome["ok"]:
        flags = " ".join(
            f"{key}={int(bool(outcome[key]))}"
            for key in ("board", "name", "footprints", "nets", "syncDisabled")
        )
        print(
            f"MACOS_COMPANION_PROBE {flags} stage={outcome['stage']} error={outcome['error']}",
            flush=True,
        )
    print("MACOS_COMPANION_LIVE_PASS" if outcome["ok"] else "MACOS_COMPANION_LIVE_FAIL", flush=True)
    return 0 if outcome["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
