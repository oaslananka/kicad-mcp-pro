"""Opt-in X11/XWayland editor placement, never automatic or PCB-mutating.

Other platforms fail closed. No window-manager packages or shell commands are
installed or executed; X11 client-message requests are a best-effort desktop
operation, not a KiCad dock or an embedded plugin API.
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EditorPlacement:
    window: int
    original: tuple[int, int, int, int]
    maximized: bool
    board_name: str


@dataclass(frozen=True)
class TileResult:
    original: EditorPlacement
    companion_position: tuple[int, int]


class _ClassHint(ctypes.Structure):
    _fields_ = [("res_name", ctypes.c_void_p), ("res_class", ctypes.c_void_p)]


class _MessageData(ctypes.Union):
    _fields_ = [("l", ctypes.c_long * 5), ("b", ctypes.c_char * 20)]


class _ClientMessage(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("serial", ctypes.c_ulong),
        ("send_event", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("window", ctypes.c_ulong),
        ("message_type", ctypes.c_ulong),
        ("format", ctypes.c_int),
        ("data", _MessageData),
    ]


class _XEvent(ctypes.Union):
    _fields_ = [("client", _ClientMessage), ("pad", ctypes.c_long * 24)]


def _pid_is_current_user(pid: int) -> bool:
    """Fail closed unless Linux procfs confirms the KiCad client's UID."""
    try:
        return Path(f"/proc/{pid}").stat().st_uid == os.getuid()
    except OSError:
        return False


class _X11:
    """One short-lived connection to the actual GNOME XWayland/X11 server."""

    def __init__(self) -> None:
        try:
            lib = ctypes.CDLL("libX11.so.6")
        except OSError as exc:
            raise RuntimeError("X11 window management is unavailable on this system.") from exc
        self.lib = lib
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XGetWindowProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.XGetWindowProperty.restype = ctypes.c_int
        lib.XGetClassHint.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_ClassHint)]
        lib.XGetClassHint.restype = ctypes.c_int
        lib.XFree.argtypes = [ctypes.c_void_p]
        lib.XFree.restype = ctypes.c_int
        lib.XTranslateCoordinates.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
        ]
        lib.XTranslateCoordinates.restype = ctypes.c_int
        lib.XGetGeometry.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        lib.XGetGeometry.restype = ctypes.c_int
        lib.XSendEvent.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_long,
            ctypes.POINTER(_XEvent),
        ]
        lib.XSendEvent.restype = ctypes.c_int
        lib.XMoveResizeWindow.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_uint,
        ]
        lib.XMoveResizeWindow.restype = ctypes.c_int
        lib.XFlush.argtypes = [ctypes.c_void_p]
        lib.XFlush.restype = ctypes.c_int
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        lib.XCloseDisplay.restype = ctypes.c_int
        self.display = lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Cannot access the desktop X11 session; no windows changed.")
        self.root = lib.XDefaultRootWindow(self.display)

    def __enter__(self) -> _X11:
        return self

    def __exit__(self, *_args: object) -> None:
        self.lib.XCloseDisplay(self.display)

    def atom(self, text: str) -> int:
        return int(self.lib.XInternAtom(self.display, text.encode(), False))

    def property(self, window: int, name: str) -> tuple[int, bytes | tuple[int, ...]]:
        kind = ctypes.c_ulong()
        fmt = ctypes.c_int()
        count = ctypes.c_ulong()
        remaining = ctypes.c_ulong()
        data = ctypes.c_void_p()
        status = self.lib.XGetWindowProperty(
            self.display,
            window,
            self.atom(name),
            0,
            4096,
            False,
            0,
            ctypes.byref(kind),
            ctypes.byref(fmt),
            ctypes.byref(count),
            ctypes.byref(remaining),
            ctypes.byref(data),
        )
        if status != 0 or remaining.value:
            if data.value:
                self.lib.XFree(data)
            return 0, ()
        if not data.value:
            # _NET_WM_STATE can validly exist with zero atoms when unmaximized.
            return (fmt.value, ()) if kind.value else (0, ())
        try:
            if fmt.value == 8:
                return 8, ctypes.string_at(data.value, count.value)
            if fmt.value == 32:
                numbers = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
                return 32, tuple(int(numbers[i]) for i in range(count.value))
            return 0, ()
        finally:
            self.lib.XFree(data)

    def window_class(self, window: int) -> str:
        hint = _ClassHint()
        if not self.lib.XGetClassHint(self.display, window, ctypes.byref(hint)):
            return ""
        try:
            return (
                ctypes.string_at(hint.res_class).decode(errors="replace") if hint.res_class else ""
            )
        finally:
            for pointer in (hint.res_name, hint.res_class):
                if pointer:
                    self.lib.XFree(ctypes.c_void_p(pointer))

    def geometry(self, window: int) -> tuple[int, int, int, int]:
        root = ctypes.c_ulong()
        unused_x, unused_y = ctypes.c_int(), ctypes.c_int()
        width, height, border, depth = (ctypes.c_uint() for _ in range(4))
        if not self.lib.XGetGeometry(
            self.display,
            window,
            ctypes.byref(root),
            ctypes.byref(unused_x),
            ctypes.byref(unused_y),
            ctypes.byref(width),
            ctypes.byref(height),
            ctypes.byref(border),
            ctypes.byref(depth),
        ):
            raise RuntimeError("Cannot read KiCad window geometry.")
        x, y = ctypes.c_int(), ctypes.c_int()
        child = ctypes.c_ulong()
        if not self.lib.XTranslateCoordinates(
            self.display,
            window,
            self.root,
            0,
            0,
            ctypes.byref(x),
            ctypes.byref(y),
            ctypes.byref(child),
        ):
            raise RuntimeError("Cannot locate KiCad's window on the monitor.")
        return x.value, y.value, width.value, height.value

    def editor(self, board_name: str) -> int:
        kind, windows = self.property(self.root, "_NET_CLIENT_LIST")
        if kind != 32 or not isinstance(windows, tuple):
            raise RuntimeError("Desktop window list unavailable; nothing arranged.")
        candidates: list[int] = []
        for window in windows:
            if self.window_class(window) != "pcbnew":
                continue
            title_kind, title = self.property(window, "_NET_WM_NAME")
            pid_kind, pids = self.property(window, "_NET_WM_PID")
            if (
                title_kind != 8
                or not isinstance(title, bytes)
                or pid_kind != 32
                or not isinstance(pids, tuple)
                or len(pids) != 1
            ):
                continue
            name = title.decode("utf-8", errors="replace")
            if (
                not name.endswith(" — PCB Editor")
                or name.split(" — PCB Editor")[0] != Path(board_name).stem
            ):
                continue
            if _pid_is_current_user(pids[0]):
                candidates.append(window)
        if len(candidates) != 1:
            raise RuntimeError("Expected one verified local KiCad PCB Editor; nothing arranged.")
        return candidates[0]

    def maximized(self, window: int) -> bool:
        kind, states = self.property(window, "_NET_WM_STATE")
        if kind != 32 or not isinstance(states, tuple):
            raise RuntimeError("Cannot verify KiCad's window state; nothing arranged.")
        horizontal = self.atom("_NET_WM_STATE_MAXIMIZED_HORZ") in states
        vertical = self.atom("_NET_WM_STATE_MAXIMIZED_VERT") in states
        if horizontal != vertical:
            raise RuntimeError("KiCad is partially maximized; restore manually before tiling.")
        return horizontal and vertical

    def set_maximized(self, window: int, enabled: bool) -> None:
        event = _XEvent()
        event.client.type = 33  # ClientMessage
        event.client.display = self.display
        event.client.window = window
        event.client.message_type = self.atom("_NET_WM_STATE")
        event.client.format = 32
        event.client.data.l[0] = 1 if enabled else 0
        event.client.data.l[1] = self.atom("_NET_WM_STATE_MAXIMIZED_HORZ")
        event.client.data.l[2] = self.atom("_NET_WM_STATE_MAXIMIZED_VERT")
        event.client.data.l[3] = 2  # user request, not a hidden background change
        if not self.lib.XSendEvent(
            self.display, self.root, False, (1 << 19) | (1 << 20), ctypes.byref(event)
        ):
            raise RuntimeError("The desktop window manager rejected the tile request.")
        self.lib.XFlush(self.display)

    def move_resize(self, window: int, geometry: tuple[int, int, int, int]) -> None:
        x, y, width, height = geometry
        if not self.lib.XMoveResizeWindow(self.display, window, x, y, width, height):
            raise RuntimeError("KiCad window move/resize request failed.")
        self.lib.XFlush(self.display)


def _layout(
    screen: tuple[int, int, int, int], sidecar_width: int
) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """Plan a readable PCB viewport and a right-edge sidecar, with no overlap."""
    left, top, right, bottom = screen
    if right - left < 1150 or bottom - top < 650 or not 280 <= sidecar_width <= 500:
        raise RuntimeError("Display is too small for a safe side-by-side layout.")
    companion = (right - sidecar_width - 12, top + 70)
    width = companion[0] - left - 22
    height = bottom - top - 90
    if width < 730 or height < 560:
        raise RuntimeError("Not enough room for the KiCad editor and Companion.")
    return (left + 8, top + 7, width, height), companion


def tile_editor(
    board_name: str, screen: tuple[int, int, int, int], sidecar_width: int
) -> TileResult:
    """Move a *verified* X11 KiCad editor only after an explicit GUI click."""
    if sys.platform != "linux" or not os.environ.get("DISPLAY"):
        raise RuntimeError("Automatic arrangement requires Linux X11/XWayland; tile manually.")
    target, companion = _layout(screen, sidecar_width)
    with _X11() as x:
        window = x.editor(board_name)
        previous = x.geometry(window)
        center = (previous[0] + previous[2] // 2, previous[1] + previous[3] // 2)
        if not (screen[0] <= center[0] < screen[2] and screen[1] <= center[1] < screen[3]):
            raise RuntimeError("KiCad is on a different display; nothing arranged.")
        if not x.maximized(window):
            raise RuntimeError("Maximize KiCad first so its window layout can be safely restored.")
        old = EditorPlacement(window, previous, True, board_name)
        try:
            x.set_maximized(window, False)
            time.sleep(0.25)
            x.move_resize(window, target)
            time.sleep(0.25)
            actual = x.geometry(window)
            if (
                abs(actual[0] - target[0]) > 55
                or abs(actual[1] - target[1]) > 55
                or abs(actual[2] - target[2]) > 30
                or abs(actual[3] - target[3]) > 30
            ):
                raise RuntimeError("Desktop did not honor the requested KiCad geometry.")
        except Exception:
            x.set_maximized(window, True)
            raise
    return TileResult(old, companion)


def restore_editor(snapshot: EditorPlacement) -> None:
    """Restore the verified original maximized KiCad window on explicit request."""
    if not snapshot.maximized:
        raise RuntimeError("Cannot safely restore an unmaximized KiCad layout.")
    with _X11() as x:
        if x.editor(snapshot.board_name) != snapshot.window:
            raise RuntimeError("KiCad window changed; cannot restore the old layout safely.")
        x.set_maximized(snapshot.window, True)
        # XSendEvent confirms transport, not actual WM state. Never report a
        # successful restore (or let the in-app Close exit) until KiCad itself
        # is observed maximized. A bounded retry handles compositor latency.
        for _attempt in range(6):
            time.sleep(0.15)
            if x.maximized(snapshot.window):
                return
        raise RuntimeError("Desktop did not confirm KiCad maximization; keep Companion open.")
