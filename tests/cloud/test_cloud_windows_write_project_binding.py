"""Cloud WRITE must map only explicit, local owner-bound project identities."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_windows_connector import resolve_owner_write_project
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

DEVICE = "11111111-1111-4111-8111-111111111111"
REGISTERED = "22222222-2222-4222-8222-222222222222"
TEST = "33333333-3333-4333-8333-333333333333"
FOREIGN = "44444444-4444-4444-8444-444444444444"


def test_explicit_owner_project_mapping_resolves_exact_requested_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_folder_browse_receiver

    base = tmp_path / "RoyalBlue54L"
    base.mkdir()
    scratch = tmp_path / "Scratch"
    scratch.mkdir()
    (scratch / "Scratch.kicad_pro").write_text("{}", encoding="utf8")
    mapping = tmp_path / "bindings.json"
    mapping.write_text(json.dumps({TEST: str(scratch / "Scratch.kicad_pro")}), encoding="utf8")
    monkeypatch.setattr(cloud_folder_browse_receiver, "default_bindings_file", lambda: mapping)

    registered = SimpleNamespace(device_id=DEVICE, project_id=REGISTERED)
    selected = SimpleNamespace(directory=base, filename_stem="RoyalBlue54L")
    assert resolve_owner_write_project(registered, selected, REGISTERED) == OperatorProject(
        DEVICE, REGISTERED, base, "RoyalBlue54L"
    )
    assert resolve_owner_write_project(registered, selected, TEST) == OperatorProject(
        DEVICE, TEST, scratch, "Scratch"
    )
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, FOREIGN)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, "not-a-project-id")
    assert selected.directory == base, "Different project mapping must not rebind the primary"


def test_removed_local_owner_mapping_denies_write_before_native_ipc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_folder_browse_receiver

    base = tmp_path / "RoyalBlue54L"
    base.mkdir()
    scratch = tmp_path / "Scratch"
    scratch.mkdir()
    project_file = scratch / "Scratch.kicad_pro"
    project_file.write_text("{}", encoding="utf8")
    mapping = tmp_path / "bindings.json"
    mapping.write_text(json.dumps({TEST: str(project_file)}), encoding="utf8")
    monkeypatch.setattr(cloud_folder_browse_receiver, "default_bindings_file", lambda: mapping)
    registered = SimpleNamespace(device_id=DEVICE, project_id=REGISTERED)
    selected = SimpleNamespace(directory=base, filename_stem="RoyalBlue54L")

    expected = resolve_owner_write_project(registered, selected, TEST)
    assert expected.directory == scratch
    mapping.unlink()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, TEST)
