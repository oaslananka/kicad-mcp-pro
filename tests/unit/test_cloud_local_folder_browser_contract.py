"""Owner-scoped folder binding, recovery and refusal cases.

These tests never open a dialog or return paths over a Cloud API.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from kicad_mcp import cloud_local_folder_browser as folder_module
from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser


def _workspace(tmp_path: Path) -> tuple[LocalFolderBrowser, Path, Path, Path, str]:
    root = tmp_path.resolve(strict=True)
    folder = root / "Project"
    folder.mkdir()
    project = folder / "Design.kicad_pro"
    project.write_text("{}", encoding="utf8")
    bindings = root / "owner-local-bindings.json"
    browser = LocalFolderBrowser([root], bindings)
    root_token = browser.list_folder("root")["folders"][0]["id"]
    folder_token = browser.list_folder(root_token)["folders"][0]["id"]
    return browser, folder, project, bindings, folder_token


def test_folder_navigation_binds_exact_kicad_file_and_rejects_wrong_owner_id(
    tmp_path: Path,
) -> None:
    browser, _folder, project, bindings, token = _workspace(tmp_path)
    project_id = str(uuid4())
    other_project_id = str(uuid4())
    assert browser.get_project_path(project_id) is None
    assert browser.bind(token, project_id)
    assert json.loads(bindings.read_text("utf8")) == {project_id: str(project)}
    assert browser.get_project_path(project_id) == str(project)
    assert browser.get_project_path(other_project_id) is None
    assert browser.get_project_path("../../untrusted") is None
    project.unlink()
    assert browser.get_project_path(project_id) is None


def test_ambiguous_folder_does_not_silently_pick_wrong_project(tmp_path: Path) -> None:
    browser, folder, project, bindings, token = _workspace(tmp_path)
    second_project = folder / "Antenna.kicad_pro"
    second_project.write_text("{}", encoding="utf8")
    assert not browser.bind(token, str(uuid4()))
    assert not bindings.exists()
    second_project.unlink()
    selected_id = str(uuid4())
    assert browser.bind(token, selected_id)
    assert browser.get_project_path(selected_id) == str(project)
    second_project.write_text("{}", encoding="utf8")
    assert browser.get_project_path(selected_id) == str(project)


def test_owner_path_lookup_rejects_corrupt_or_unsafe_stored_values(tmp_path: Path) -> None:
    browser, folder, project, bindings, _token = _workspace(tmp_path)
    project_id = str(uuid4())
    wrong_kind = folder / "footprint.txt"
    wrong_kind.write_text("other", encoding="utf8")
    for payload in [
        "not-json",
        "[]",
        json.dumps({project_id: 3}),
        json.dumps({project_id: "relative/Design.kicad_pro"}),
        json.dumps({project_id: str(wrong_kind)}),
        json.dumps({project_id: str(folder / "missing.kicad_pro")}),
        json.dumps({project_id: "x" * 2049}),
    ]:
        bindings.write_text(payload, encoding="utf8")
        assert browser.get_project_path(project_id) is None
    bindings.write_text(json.dumps({project_id: str(project)}), encoding="utf8")
    assert browser.get_project_path(project_id) == str(project)


def test_owner_path_lookup_rejects_symlink_kicad_file(tmp_path: Path) -> None:
    browser, folder, project, bindings, _token = _workspace(tmp_path)
    linked = folder / "Linked.kicad_pro"
    try:
        linked.symlink_to(project)
    except (OSError, NotImplementedError):
        pytest.skip("Creating file symlinks is not permitted on this host")
    project_id = str(uuid4())
    bindings.write_text(json.dumps({project_id: str(linked)}), encoding="utf8")
    assert browser.get_project_path(project_id) is None


def test_native_folder_token_is_path_free_and_rechecks_removed_directory(tmp_path: Path) -> None:
    browser, folder, _project, bindings, _token = _workspace(tmp_path)
    selected = browser.choose_native(lambda: folder)
    assert selected["status"] == "selected"
    token = selected["folderId"]
    linked = browser.list_folder(token)
    assert linked["project"] is True
    assert linked["parentId"] is None
    assert linked["folders"] == []
    assert str(folder) not in json.dumps(linked)
    folder.rename(tmp_path / "Moved")
    with pytest.raises(ValueError, match="folder_unavailable"):
        browser.list_folder(token)
    assert not browser.bind(token, str(uuid4()))
    assert not bindings.exists()


def test_permission_denied_folder_refuses_browse_selection_and_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, folder, _project, bindings, token = _workspace(tmp_path)

    def permission_denied(_path: Path):
        raise PermissionError("User-owned folder no longer readable")

    with monkeypatch.context() as m:
        m.setattr(folder_module.os, "scandir", permission_denied)
        with pytest.raises(ValueError, match="folder_unavailable"):
            browser.list_folder(token)
        assert browser.choose_native(lambda: folder) == {"status": "invalid"}
        assert not browser.bind(token, str(uuid4()))
    assert not bindings.exists()


def test_invalid_owner_binding_store_is_not_overwritten(tmp_path: Path) -> None:
    browser, folder, _project, bindings, _token = _workspace(tmp_path)
    chosen = browser.choose_native(lambda: folder)
    bindings.write_text("[]", encoding="utf8")
    with pytest.raises(ValueError, match="invalid_binding_store"):
        browser.bind(chosen["folderId"], str(uuid4()))
    assert bindings.read_text("utf8") == "[]"


def test_token_quota_expiration_clears_old_navigation_tokens(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser, _folder, _project, _bindings, _token = _workspace(tmp_path)
    # Isolate the quota behavior from normal 2,048-token production capacity.
    with monkeypatch.context() as m:
        m.setattr(folder_module, "MAX_TOKENS", len(browser._paths) + 1)
        browser.list_folder("root")
        with pytest.raises(ValueError, match="folder_session_expired"):
            browser.list_folder("root")
    assert set(browser._paths) == {"root"}
    assert browser.list_folder("root")["folders"]


def test_browse_lists_at_most_35_folders_and_signals_more(tmp_path: Path) -> None:
    root = tmp_path.resolve(strict=True)
    for index in range(38):
        (root / f"project-{index:02}").mkdir()
    browser = LocalFolderBrowser([root], root / "bindings.json")
    root_id = browser.list_folder("root")["folders"][0]["id"]
    listing = browser.list_folder(root_id)
    assert len(listing["folders"]) == folder_module.MAX_CHILDREN
    assert listing["more"] is True
    assert all(Path(item["name"]).is_absolute() is False for item in listing["folders"])
