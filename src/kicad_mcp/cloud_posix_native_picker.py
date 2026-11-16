"""Owner-visible POSIX project directory chooser for a signed Cloud session.

Never runs on a server or unattended daemon; never sends filesystem paths to Cloud.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

_TITLE = "Choose your local KiCad project folder"
_TIMEOUT = 120


def native_picker_available() -> bool:
    """Advertise Cloud Browse only when an owner desktop can show a folder UI."""
    if sys.platform == "darwin":
        return shutil.which("osascript") is not None
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return False
        return (
            shutil.which("zenity") is not None or importlib.util.find_spec("_tkinter") is not None
        )
    return False


def _select_with_tkinter() -> Path | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        dialog = tk.Tk()
        dialog.withdraw()
        try:
            chosen = filedialog.askdirectory(parent=dialog, title=_TITLE, mustexist=True)
        finally:
            dialog.destroy()
        return Path(chosen) if chosen else None
    except Exception as exc:
        raise OSError("No graphical project folder chooser is available") from exc


def choose_project_folder() -> Path | None:
    """Return the owner's GUI-selected folder or None on explicit cancellation."""
    if not native_picker_available():
        raise OSError("A graphical project folder chooser is unavailable on this device")
    cmd: list[str] = []
    if sys.platform == "darwin":
        executable = shutil.which("osascript")
        if executable is None:
            raise OSError("No macOS folder chooser is available")
        cmd = [
            executable,
            "-e",
            'POSIX path of (choose folder with prompt "' + _TITLE + '")',
        ]
    elif sys.platform.startswith("linux"):
        executable = shutil.which("zenity")
        if executable is None:
            return _select_with_tkinter()
        cmd = [
            executable,
            "--file-selection",
            "--directory",
            "--title=" + _TITLE,
        ]
    else:
        raise OSError("POSIX native project folder picker requires macOS or Linux")
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
            timeout=_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError("The native project folder chooser could not finish") from exc
    if result.returncode != 0:
        if sys.platform == "darwin":
            if "(-128)" in result.stderr:
                return None
        elif result.returncode == 1 and not result.stdout.strip():
            return None
        raise OSError("The native project folder chooser failed")
    selected = result.stdout.strip()
    return Path(selected) if selected else None
