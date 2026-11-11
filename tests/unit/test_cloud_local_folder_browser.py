from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest

from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser


def test_browse_and_bind_local_project_without_leaking_paths(tmp_path: Path) -> None:
    desktop = tmp_path / "Desktop"
    project = desktop / "Şema-Board"
    project.mkdir(parents=True)
    (project / "test.kicad_pro").write_text("{}", encoding="utf8")
    db = tmp_path / "bindings.json"
    browse = LocalFolderBrowser([desktop], db)

    home = browse.list_folder("root")
    assert "Desktop" in [i["name"] for i in home["folders"]]
    desktop_id = home["folders"][0]["id"]
    second = browse.list_folder(desktop_id)
    assert second["project"] is False
    assert second["folders"][0]["name"] == "Şema-Board"
    assert second["folders"][0]["project"] is True
    project_id = second["folders"][0]["id"]
    project_info = browse.list_folder(project_id)
    assert project_info["parentId"] == desktop_id
    assert project_info["project"] is True
    assert str(tmp_path) not in json.dumps(home) + json.dumps(second) + json.dumps(project_info)
    assert db.exists() is False

    unique_id = str(uuid4())
    assert browse.bind(project_id, unique_id)
    assert json.loads(db.read_text(encoding="utf8")) == {unique_id: str(project)}
    assert browse.bind(desktop_id, str(uuid4())) is False
    assert browse.bind("fake", str(uuid4())) is False
    assert browse.bind(project_id, "../../bad") is False


def test_reject_symlink_outside_root_and_unknown_tokens(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.kicad_pro").touch()
    try:
        (root / "out").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink privilege not available")
    browse = LocalFolderBrowser([root], tmp_path / "bind.json")
    root_id = browse.list_folder("root")["folders"][0]["id"]
    assert browse.list_folder(root_id)["folders"] == []
    with pytest.raises(ValueError, match="unknown_folder"):
        browse.list_folder("outside")


def test_no_persist_without_real_kicad_project(tmp_path: Path) -> None:
    root = tmp_path / "Desktop"
    folder = root / "Only-a-PCB"
    folder.mkdir(parents=True)
    (folder / "sample.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")
    browse = LocalFolderBrowser([root], tmp_path / "bindings.json")
    root_id = browse.list_folder("root")["folders"][0]["id"]
    child_id = browse.list_folder(root_id)["folders"][0]["id"]
    assert browse.list_folder(child_id)["project"] is False
    assert browse.bind(child_id, str(uuid4())) is False
    assert not (tmp_path / "bindings.json").exists()
