"""Modern Windows Explorer project-folder selection on an interactive user STA thread.

Only the selected folder is returned to the local device process.
Do not use this module in a headless service or a Cloud server.
"""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

FOS_PICKFOLDERS = 0x20
FOS_FORCEFILESYSTEM = 0x40
FOS_PATHMUSTEXIST = 0x800
SIGDN_FILESYSPATH = 0x80058000
CANCELLED_HRESULT = 0x800704C7


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> GUID:
    return GUID.from_buffer_copy(UUID(value).bytes_le)


def _checked(hr: int, operation: str) -> None:
    if hr < 0:
        raise OSError(f"Windows folder chooser failed during {operation}: 0x{hr & 0xFFFFFFFF:08x}")


def check_native_dialog_api() -> bool:
    """Noninteractive Windows capability check for local smoke tests."""
    if sys.platform != "win32":
        return False
    ole = ctypes.WinDLL("ole32.dll", winmode=0x800)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    hr = ole.CoInitializeEx(None, 2)
    if hr not in (0, 1):
        return False
    try:
        clsid = _guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
        iid = _guid("D57C7288-D4AD-4768-BE02-9D969532D960")
        pointer = ctypes.c_void_p()
        ole.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole.CoCreateInstance.restype = ctypes.c_long
        result = ole.CoCreateInstance(
            ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(pointer)
        )
        if result < 0:
            return False
        try:
            get_options = _method(pointer, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
            set_options = _method(pointer, 9, ctypes.c_long, wintypes.DWORD)
            set_title = _method(pointer, 17, ctypes.c_long, wintypes.LPCWSTR)
            set_label = _method(pointer, 18, ctypes.c_long, wintypes.LPCWSTR)
            flags = wintypes.DWORD(0)
            _checked(get_options(pointer, ctypes.byref(flags)), "options")
            _checked(
                set_options(
                    pointer, flags.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
                ),
                "set_options",
            )
            _checked(set_title(pointer, "Select KiCad project folder"), "set_title")
            _checked(set_label(pointer, "Select folder"), "set_button")
            return True
        finally:
            _method(pointer, 2, ctypes.c_ulong)(pointer)
            pointer = ctypes.c_void_p()
    finally:
        ole.CoUninitialize()


def _method(pointer: ctypes.c_void_p, index: int, result: type, *args: type) -> Callable[..., int]:
    # COM vtable functions use Windows stdcall and the interface pointer
    # as their first argument.
    vtable = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(result, ctypes.c_void_p, *args)(vtable[index])


def choose_project_folder() -> Path | None:
    """Show native Explorer-style IFileOpenDialog in folder-pick mode.

    None means the owner cancelled. All failures are explicit, never silently
    replaced by a text or browser-side filesystem input.
    """
    if sys.platform != "win32":
        raise OSError("Native Windows folder picker requires Windows")
    ole = ctypes.WinDLL("ole32.dll", winmode=0x800)
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoUninitialize.argtypes = []
    hr = ole.CoInitializeEx(None, 2)
    if hr not in (0, 1):
        raise OSError("Unable to initialize Windows folder picker apartment")
    dialog = ctypes.c_void_p()
    shellitem = ctypes.c_void_p()
    name_pointer = ctypes.c_void_p()
    try:
        ole.CoCreateInstance.argtypes = [
            ctypes.POINTER(GUID),
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(GUID),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        ole.CoCreateInstance.restype = ctypes.c_long
        _checked(
            ole.CoCreateInstance(
                ctypes.byref(_guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")),
                None,
                1,
                ctypes.byref(_guid("D57C7288-D4AD-4768-BE02-9D969532D960")),
                ctypes.byref(dialog),
            ),
            "create",
        )
        get_options = _method(dialog, 10, ctypes.c_long, ctypes.POINTER(wintypes.DWORD))
        set_options = _method(dialog, 9, ctypes.c_long, wintypes.DWORD)
        set_title = _method(dialog, 17, ctypes.c_long, wintypes.LPCWSTR)
        set_label = _method(dialog, 18, ctypes.c_long, wintypes.LPCWSTR)
        show = _method(dialog, 3, ctypes.c_long, wintypes.HWND)
        get_result = _method(dialog, 20, ctypes.c_long, ctypes.POINTER(ctypes.c_void_p))
        options = wintypes.DWORD(0)
        _checked(get_options(dialog, ctypes.byref(options)), "options")
        _checked(
            set_options(
                dialog, options.value | FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST
            ),
            "set_options",
        )
        _checked(set_title(dialog, "Select KiCad project folder"), "set_title")
        _checked(set_label(dialog, "Select folder"), "set_button")
        hr = show(dialog, None)
        if (hr & 0xFFFFFFFF) == CANCELLED_HRESULT:
            return None
        _checked(hr, "show")
        _checked(get_result(dialog, ctypes.byref(shellitem)), "result")
        display_name = _method(
            shellitem, 5, ctypes.c_long, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
        )
        _checked(display_name(shellitem, SIGDN_FILESYSPATH, ctypes.byref(name_pointer)), "path")
        selected = Path(ctypes.wstring_at(name_pointer))
        if not selected.is_dir():
            raise OSError("Choose an existing project folder")
        return selected
    finally:
        if name_pointer:
            ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
            ole.CoTaskMemFree(name_pointer)
        if shellitem:
            _method(shellitem, 2, ctypes.c_ulong)(shellitem)
        if dialog:
            _method(dialog, 2, ctypes.c_ulong)(dialog)
        ole.CoUninitialize()
