"""Owner-visible POSIX project directory chooser for a signed Cloud session.

Never runs on a server or unattended daemon; never sends filesystem paths to Cloud.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import shutil
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


async def _capture_native_dialog(argv: list[str]) -> tuple[int, str, str]:
    """Run an owner-visible platform chooser with argument separation and a deadline."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise OSError("The native project folder chooser could not start") from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=_TIMEOUT)
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise OSError("The native project folder chooser timed out") from exc
    if process.returncode is None:
        raise OSError("The native project folder chooser did not exit")
    return (
        process.returncode,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )


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
    status, stdout, stderr = asyncio.run(_capture_native_dialog(cmd))
    if status != 0:
        if sys.platform == "darwin" and "(-128)" in stderr:
            return None
        if sys.platform.startswith("linux") and status == 1 and not stdout.strip():
            return None
        raise OSError("The native project folder chooser failed")
    selected = stdout.strip()
    return Path(selected) if selected else None
