"""Native Win32 owner-confirmed local project path reference acceptance."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp import cloud_windows_local_selection as selection
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Win32 owner-scoped path required")


@pytest.fixture
def project_fixture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[WindowsRegisteredProject, dict[tuple[str, str], bytes], Path]:
    folder = tmp_path / "boards"
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text("{}", encoding="utf-8")
    project = WindowsRegisteredProject(
        registration_id="a" * 32,
        record_id="b" * 32,
        origin="https://cloud.example",
        owner_sub="provider|owner-42",
        device_id="19ee4be9-0aec-448e-9873-721ae113ec02",
        fingerprint="f" * 64,
        project_id="29ee4be9-0aec-448e-9873-721ae113ec02",
        filename_stem="demo",
    )
    store: dict[tuple[str, str], bytes] = {}

    def create(rec: str, part: str, blob: bytes) -> None:
        key = (rec, part)
        if key in store:
            raise LocalApprovalDeniedError("duplicate")
        store[key] = blob

    def read(rec: str, part: str) -> bytes | None:
        return store.get((rec, part))

    monkeypatch.setattr(
        selection,
        "inspect_project_reference",
        lambda **_kw: SimpleNamespace(fingerprint=project.fingerprint),
    )
    monkeypatch.setattr(selection, "create_credential", create)
    monkeypatch.setattr(selection, "read_credential", read)
    return project, store, folder


def test_selected_project_requires_owner_confirmation_before_vault_record(
    project_fixture,
) -> None:
    project, store, folder = project_fixture
    reviewed: list[Path] = []
    output = selection.bind_owner_selected_project(
        project,
        folder,
        owner_confirm=lambda path: reviewed.append(path) or True,
    )
    assert reviewed == [folder]
    assert output.directory == folder
    assert output.project_id == project.project_id
    assert list(store) == [(project.registration_id, "project_path")]
    saved = json.loads(next(iter(store.values())))
    assert saved["directory"] == str(folder)
    assert saved["projectId"] == project.project_id
    assert not any(key.lower() in saved for key in ("permissions", "allowed", "grant", "enabled"))


def test_cancelled_owner_confirmation_has_no_vault_write(project_fixture) -> None:
    project, store, folder = project_fixture
    with pytest.raises(LocalApprovalDeniedError, match="owner did not approve"):
        selection.bind_owner_selected_project(project, folder, owner_confirm=lambda _: False)
    assert not store


def test_absent_kicad_project_refuses_before_confirmation(project_fixture, tmp_path) -> None:
    project, store, _folder = project_fixture
    unused = tmp_path / "empty"
    unused.mkdir()
    with pytest.raises(LocalApprovalDeniedError):
        selection.bind_owner_selected_project(
            project,
            unused,
            owner_confirm=lambda _path: pytest.fail("No confirmation without KiCad file"),
        )
    assert not store


@pytest.mark.parametrize(
    "alter",
    [
        lambda d: dict(d, origin="https://attacker.example"),
        lambda d: dict(d, directory="C:/Windows"),
        lambda d: dict(d, extra="grant"),
        lambda d: dict(d, projectId="39ee4be9-0aec-448e-9873-721ae113ec02"),
    ],
)
def test_corrupted_local_vault_path_reference_is_denied(project_fixture, alter) -> None:
    project, store, folder = project_fixture
    selection.bind_owner_selected_project(project, folder, owner_confirm=lambda _: True)
    key = (project.registration_id, "project_path")
    document = json.loads(store[key])
    store[key] = json.dumps(alter(document)).encode()
    with pytest.raises(LocalApprovalDeniedError):
        selection.inspect_owner_selected_project(project)


def test_recheck_denies_when_selected_project_file_disappears(project_fixture) -> None:
    project, store, folder = project_fixture
    selection.bind_owner_selected_project(project, folder, owner_confirm=lambda _: True)
    (folder / "demo.kicad_pro").unlink()
    with pytest.raises(LocalApprovalDeniedError):
        selection.inspect_owner_selected_project(project)
    assert list(store) == [(project.registration_id, "project_path")]


def test_binding_fails_if_local_credential_slot_already_exists(project_fixture) -> None:
    project, store, folder = project_fixture
    store[(project.registration_id, "project_path")] = b"original"
    with pytest.raises(LocalApprovalDeniedError):
        selection.bind_owner_selected_project(project, folder, owner_confirm=lambda _: True)
    assert store[(project.registration_id, "project_path")] == b"original"


def test_path_is_never_accepted_as_remote_authorization(project_fixture) -> None:
    project, _store, folder = project_fixture
    selected = selection.bind_owner_selected_project(project, folder, owner_confirm=lambda _: True)
    assert not hasattr(selected, "enabled")
    assert not hasattr(selected, "authorized")
    assert not hasattr(selected, "signing_key")
    assert not hasattr(selected, "cloud_grant")
