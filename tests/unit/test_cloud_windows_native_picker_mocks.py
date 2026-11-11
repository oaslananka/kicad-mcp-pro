"""Headless, cross-platform tests for the owner-initiated Windows COM folder picker.

The real dialog is never shown: a narrow fake COM vtable models the same
resource cleanup, error handling and folder-only selection contract.
"""

from __future__ import annotations

import ctypes
import tempfile
import unittest
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from kicad_mcp import cloud_windows_native_picker as picker


class SimulatedDialog:
    def __init__(
        self,
        folder: Path,
        *,
        init_hr: int = 0,
        create_hr: int = 0,
        options_hr: int = 0,
        show_hr: int = 0,
        result_hr: int = 0,
    ) -> None:
        self.folder = folder
        self.create_hr = create_hr
        self.options_hr = options_hr
        self.show_hr = show_hr
        self.result_hr = result_hr
        self.flags: list[int] = []
        self.titles: list[str] = []
        self.labels: list[str] = []
        self.release_calls: list[int] = []
        self.display_name_kinds: list[int] = []
        self.ole = SimpleNamespace(
            CoInitializeEx=Mock(return_value=init_hr),
            CoUninitialize=Mock(),
            CoCreateInstance=Mock(side_effect=self.create),
            CoTaskMemFree=Mock(),
        )

    def create(
        self, _clsid: object, _outer: object, _context: object, _iid: object, result_pointer: object
    ) -> int:
        if self.create_hr == 0:
            ctypes.cast(result_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(
                0x1000
            )
        return self.create_hr

    def get_options(self, _dialog: object, flags_pointer: object) -> int:
        ctypes.cast(flags_pointer, ctypes.POINTER(wintypes.DWORD))[0] = wintypes.DWORD(3)
        return self.options_hr

    def set_options(self, _dialog: object, flags: int) -> int:
        self.flags.append(flags)
        return 0

    def set_title(self, _dialog: object, title: str) -> int:
        self.titles.append(title)
        return 0

    def set_label(self, _dialog: object, label: str) -> int:
        self.labels.append(label)
        return 0

    def show(self, _dialog: object, _owner: object) -> int:
        return self.show_hr

    def get_result(self, _dialog: object, item_pointer: object) -> int:
        if self.result_hr == 0:
            ctypes.cast(item_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(0x2000)
        return self.result_hr

    def get_display_name(self, _item: object, kind: int, output_pointer: object) -> int:
        self.display_name_kinds.append(kind)
        ctypes.cast(output_pointer, ctypes.POINTER(ctypes.c_void_p))[0] = ctypes.c_void_p(0x3000)
        return 0

    def release(self, pointer: ctypes.c_void_p) -> int:
        self.release_calls.append(pointer.value)
        return 0

    def method(self, _pointer: object, index: int, *_signature: object) -> Callable[..., int]:
        methods = {
            2: self.release,
            3: self.show,
            5: self.get_display_name,
            9: self.set_options,
            10: self.get_options,
            17: self.set_title,
            18: self.set_label,
            20: self.get_result,
        }
        return methods[index]

    @contextmanager
    def installed(self) -> Iterator[None]:
        with ExitStack() as stack:
            stack.enter_context(patch.object(picker.sys, "platform", "win32"))
            stack.enter_context(
                patch.object(picker.ctypes, "WinDLL", return_value=self.ole, create=True)
            )
            stack.enter_context(patch.object(picker, "_method", side_effect=self.method))
            stack.enter_context(
                patch.object(picker.ctypes, "wstring_at", return_value=str(self.folder))
            )
            yield

    def assert_folder_only_configuration(self, test: unittest.TestCase) -> None:
        test.assertTrue(self.flags)
        bits = picker.FOS_PICKFOLDERS | picker.FOS_FORCEFILESYSTEM | picker.FOS_PATHMUSTEXIST
        test.assertEqual(self.flags[-1] & bits, bits)
        test.assertEqual(self.titles[-1], "Select KiCad project folder")
        test.assertEqual(self.labels[-1], "Select folder")


class NativePickerComContractTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.folder = Path(temp.name).resolve(strict=True)

    def test_com_capability_probe_sets_folder_flags_then_releases(self) -> None:
        fake = SimulatedDialog(self.folder)
        with fake.installed():
            self.assertTrue(picker.check_native_dialog_api())
        fake.assert_folder_only_configuration(self)
        self.assertEqual(fake.release_calls, [0x1000])
        fake.ole.CoInitializeEx.assert_called_once_with(None, 2)
        fake.ole.CoUninitialize.assert_called_once()

    def test_com_capability_probe_fails_closed_before_or_after_creation(self) -> None:
        for init_hr, create_hr in ((-1, 0), (0, -1)):
            with self.subTest(init_hr=init_hr, create_hr=create_hr):
                fake = SimulatedDialog(self.folder, init_hr=init_hr, create_hr=create_hr)
                with fake.installed():
                    self.assertFalse(picker.check_native_dialog_api())
                self.assertEqual(fake.ole.CoUninitialize.call_count, int(init_hr == 0))

    def test_capability_probe_com_option_failure_releases_dialog(self) -> None:
        fake = SimulatedDialog(self.folder, options_hr=-2)
        with fake.installed():
            with self.assertRaisesRegex(OSError, "during options"):
                picker.check_native_dialog_api()
        self.assertEqual(fake.release_calls, [0x1000])
        fake.ole.CoUninitialize.assert_called_once()

    def test_owner_selection_returns_existing_folder_and_cleans_all_com(self) -> None:
        fake = SimulatedDialog(self.folder)
        with fake.installed():
            selected = picker.choose_project_folder()
        self.assertEqual(selected, self.folder)
        fake.assert_folder_only_configuration(self)
        self.assertEqual(fake.display_name_kinds, [picker.SIGDN_FILESYSPATH])
        self.assertEqual(fake.release_calls, [0x2000, 0x1000])
        fake.ole.CoTaskMemFree.assert_called_once()
        fake.ole.CoUninitialize.assert_called_once()

    def test_user_cancellation_is_noop_and_releases_dialog(self) -> None:
        fake = SimulatedDialog(self.folder, show_hr=picker.CANCELLED_HRESULT)
        with fake.installed():
            self.assertIsNone(picker.choose_project_folder())
        self.assertEqual(fake.release_calls, [0x1000])
        fake.ole.CoTaskMemFree.assert_not_called()
        fake.ole.CoUninitialize.assert_called_once()

    def test_missing_selected_directory_is_rejected_with_cleanup(self) -> None:
        fake = SimulatedDialog(self.folder / "no-longer-present")
        with fake.installed():
            with self.assertRaisesRegex(OSError, "existing project folder"):
                picker.choose_project_folder()
        self.assertEqual(fake.release_calls, [0x2000, 0x1000])
        fake.ole.CoTaskMemFree.assert_called_once()
        fake.ole.CoUninitialize.assert_called_once()

    def test_com_creation_and_show_fail_closed_with_cleanup(self) -> None:
        for create_hr, show_hr in ((-2, 0), (0, -3)):
            with self.subTest(create_hr=create_hr, show_hr=show_hr):
                fake = SimulatedDialog(self.folder, create_hr=create_hr, show_hr=show_hr)
                with fake.installed():
                    with self.assertRaisesRegex(OSError, "during (create|show)"):
                        picker.choose_project_folder()
                fake.ole.CoUninitialize.assert_called_once()
                self.assertEqual(fake.release_calls, [0x1000] if create_hr == 0 else [])

    def test_com_apartment_failure_is_explicit_without_releasing_uninitialized_com(self) -> None:
        fake = SimulatedDialog(self.folder, init_hr=-3)
        with fake.installed():
            with self.assertRaisesRegex(OSError, "initialize Windows folder picker"):
                picker.choose_project_folder()
        fake.ole.CoUninitialize.assert_not_called()

    def test_get_result_failure_closes_dialog_without_shellitem(self) -> None:
        fake = SimulatedDialog(self.folder, result_hr=-3)
        with fake.installed():
            with self.assertRaisesRegex(OSError, "during result"):
                picker.choose_project_folder()
        self.assertEqual(fake.release_calls, [0x1000])
        fake.ole.CoTaskMemFree.assert_not_called()

    def test_nonwindows_hosts_never_start_a_picker(self) -> None:
        with patch.object(picker.sys, "platform", "linux"):
            self.assertFalse(picker.check_native_dialog_api())
            with self.assertRaisesRegex(OSError, "requires Windows"):
                picker.choose_project_folder()


if __name__ == "__main__":
    unittest.main()
