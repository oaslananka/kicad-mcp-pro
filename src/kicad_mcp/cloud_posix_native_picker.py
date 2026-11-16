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
from typing import Literal

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


async def _start_native_dialog(
    platform: Literal["darwin", "linux"],
) -> asyncio.subprocess.Process:
    """Launch only the allowlisted operating-system GUI chooser."""
    if platform == "darwin":
        return await asyncio.create_subprocess_exec(
            "/usr/bin/osascript",
            "-e",
            'POSIX path of (choose folder with prompt "Choose your local KiCad project folder")',
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    return await asyncio.create_subprocess_exec(
        "zenity",
        "--file-selection",
        "--directory",
        "--title=Choose your local KiCad project folder",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def _capture_native_dialog(platform: Literal["darwin", "linux"]) -> tuple[int, str, str]:
    """Capture the chooser result with a deadline and fail-closed cleanup."""
    try:
        process = await _start_native_dialog(platform)
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
    platform: Literal["darwin", "linux"] = "darwin"
    if sys.platform == "darwin":
        if shutil.which("osascript") is None:
            raise OSError("No macOS folder chooser is available")
    elif sys.platform.startswith("linux"):
        if shutil.which("zenity") is None:
            return _select_with_tkinter()
        platform = "linux"
    else:
        raise OSError("POSIX native project folder picker requires macOS or Linux")
    status, stdout, stderr = asyncio.run(_capture_native_dialog(platform))
    if status != 0:
        if sys.platform == "darwin" and "(-128)" in stderr:
            return None
        if sys.platform.startswith("linux") and status == 1 and not stdout.strip():
            return None
        raise OSError("The native project folder chooser failed")
    selected = stdout.strip()
    return Path(selected) if selected else None
