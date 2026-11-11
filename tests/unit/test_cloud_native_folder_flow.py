"""Unit checks for the native picker selection contract (no GUI prompts)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
from kicad_mcp.cloud_windows_native_picker import check_native_dialog_api


class NativeFolderSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        # macOS may expose /var as a symlink to /private/var; binding paths are
        # canonicalized by LocalFolderBrowser before being stored.
        self.root = Path(self.temporary.name).resolve(strict=True)
        self.outside = self.root / "different_drive_simulation"
        self.outside.mkdir()
        self.project = self.outside / "KiCad (A)"
        self.project.mkdir()
        (self.project / "Design.kicad_pro").write_text("{}", encoding="utf8")
        self.bindings = self.root / "local-bindings.json"
        # The owner should be able to select folders outside any
        # pre-configured browser root via the native dialog.
        self.browser = LocalFolderBrowser([], self.bindings)

    def test_real_windows_picker_com_available_without_opening_any_dialog(self) -> None:
        import sys

        if sys.platform == "win32":
            self.assertTrue(check_native_dialog_api())

    def test_selection_only_returns_project_names_and_opaque_ids(self) -> None:
        chosen = self.browser.choose_native(lambda: self.project)
        self.assertEqual(chosen["status"], "selected")
        self.assertEqual(chosen["name"], self.project.name)
        self.assertEqual(len(chosen["projects"]), 1)
        self.assertEqual(chosen["projects"][0]["name"], "Design")
        self.assertNotIn(str(self.project), json.dumps(chosen))
        project_id = str(uuid4())
        self.assertTrue(self.browser.bind(chosen["projects"][0]["id"], project_id))
        self.assertEqual(
            json.loads(self.bindings.read_text("utf8")),
            {project_id: str(self.project / "Design.kicad_pro")},
        )

    def test_multiple_projects_in_same_folder_get_distinct_bindings(self) -> None:
        (self.project / "Antenna.kicad_pro").write_text("{}", encoding="utf8")
        chosen = self.browser.choose_native(lambda: self.project)
        self.assertEqual([item["name"] for item in chosen["projects"]], ["Antenna", "Design"])
        first_id = str(uuid4())
        second_id = str(uuid4())
        self.assertTrue(self.browser.bind(chosen["projects"][0]["id"], first_id))
        self.assertTrue(self.browser.bind(chosen["projects"][1]["id"], second_id))
        self.assertEqual(
            json.loads(self.bindings.read_text("utf8")),
            {
                first_id: str(self.project / "Antenna.kicad_pro"),
                second_id: str(self.project / "Design.kicad_pro"),
            },
        )
        self.assertNotIn(str(self.project), json.dumps(chosen))

    def test_files_instead_of_folder_selection_are_rejected(self) -> None:
        project_file = self.project / "Design.kicad_pro"
        self.assertEqual(self.browser.choose_native(lambda: project_file), {"status": "invalid"})
        self.assertFalse(self.bindings.exists())

    def test_removed_project_before_confirmation_does_not_bind(self) -> None:
        chosen = self.browser.choose_native(lambda: self.project)
        (self.project / "Design.kicad_pro").unlink()
        self.assertFalse(self.browser.bind(chosen["projects"][0]["id"], str(uuid4())))
        self.assertFalse(self.bindings.exists())

    def test_cancel_is_noop(self) -> None:
        self.assertEqual(self.browser.choose_native(lambda: None), {"status": "cancelled"})
        self.assertFalse(self.bindings.exists())

    def test_nonproject_folder_is_rejected(self) -> None:
        self.assertEqual(self.browser.choose_native(lambda: self.outside), {"status": "invalid"})
        self.assertFalse(self.bindings.exists())

    def test_stale_selection_is_rejected_before_binding(self) -> None:
        chosen = self.browser.choose_native(lambda: self.project)
        (self.project / "Design.kicad_pro").unlink()
        self.assertFalse(self.browser.bind(chosen["folderId"], str(uuid4())))
        self.assertFalse(self.bindings.exists())


if __name__ == "__main__":
    unittest.main()
