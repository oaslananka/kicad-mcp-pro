"""Cloud WRITE must map only explicit, local owner-bound project identities."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp import cloud_windows_scoped_projects as scoped
from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_windows_connector import (
    _approved_write_target,
    resolve_owner_write_project,
)
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_transaction_guard import run_offline_guarded_native_write

DEVICE = "11111111-1111-4111-8111-111111111111"
REGISTERED = "22222222-2222-4222-8222-222222222222"
TEST = "33333333-3333-4333-8333-333333333333"
FOREIGN = "44444444-4444-4444-8444-444444444444"


@pytest.fixture
def scoped_store(monkeypatch) -> dict[tuple[str, str], bytes]:
    store = {}
    monkeypatch.setattr(scoped, "read_credential", lambda slot, part: store.get((slot, part)))
    monkeypatch.setattr(
        scoped, "create_credential", lambda slot, part, blob: store.__setitem__((slot, part), blob)
    )
    monkeypatch.setattr(
        scoped,
        "read_windows_project_presence",
        lambda directory, stem: {"projectPresent": (directory / (stem + ".kicad_pro")).is_file()},
    )
    return store


def registered_project() -> WindowsRegisteredProject:
    return WindowsRegisteredProject(
        "a" * 32,
        "b" * 32,
        "https://cloud.example",
        "owner",
        DEVICE,
        "c" * 64,
        REGISTERED,
        "Registered",
    )


def test_explicit_owner_project_mapping_resolves_exact_requested_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scoped_store
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

    registered = registered_project()
    selected = SimpleNamespace(directory=base, filename_stem="RoyalBlue54L")
    assert resolve_owner_write_project(registered, selected, REGISTERED) == OperatorProject(
        DEVICE, REGISTERED, base, "RoyalBlue54L"
    )
    with pytest.raises(LocalWriteDeniedError):
        resolve_owner_write_project(registered, selected, TEST)
    assert scoped.save(registered, TEST, scratch / "Scratch.kicad_pro")
    assert resolve_owner_write_project(registered, selected, TEST) == OperatorProject(
        DEVICE, TEST, scratch, "Scratch"
    )
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, FOREIGN)
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, "not-a-project-id")
    assert selected.directory == base, "Different project mapping must not rebind the primary"


def test_removed_local_owner_mapping_denies_write_before_native_ipc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scoped_store
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
    registered = registered_project()
    selected = SimpleNamespace(directory=base, filename_stem="RoyalBlue54L")

    assert scoped.save(registered, TEST, project_file)
    expected = resolve_owner_write_project(registered, selected, TEST)
    assert expected.directory == scratch
    scoped_store.pop((scoped._slot(scoped._identity(registered, TEST)), "secondary_project"))
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        resolve_owner_write_project(registered, selected, TEST)


@pytest.mark.skipif(os.name != "nt", reason="Win32 native project lock required")
@pytest.mark.parametrize("revocation", ["remove_binding", "change_target"])
def test_owner_binding_revoked_during_native_stage_discards_before_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, revocation: str, scoped_store
) -> None:
    """Exercise actual Win32 project lock and owner binding checks, not a remote WSS race."""
    from kicad_mcp import cloud_folder_browse_receiver, cloud_windows_connector

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    (tmp_path / "KiCadMCPPro" / "Cloud" / "write-markers").mkdir(parents=True)
    base = tmp_path / "Registered"
    base.mkdir()
    scratch = tmp_path / "Disposable"
    scratch.mkdir()
    test_file = scratch / "Disposable.kicad_pro"
    test_file.write_text("{}", encoding="utf-8")
    board = scratch / "Disposable.kicad_pcb"
    original = b"(kicad_pcb (version 20250114) (generator pcbnew))\n"
    board.write_bytes(original)
    alternative = tmp_path / "Other"
    alternative.mkdir()
    alternative_file = alternative / "Other.kicad_pro"
    alternative_file.write_text("{}", encoding="utf-8")

    mapping = tmp_path / "bindings.json"
    mapping.write_text(json.dumps({TEST: str(test_file)}), encoding="utf-8")
    monkeypatch.setattr(cloud_folder_browse_receiver, "default_bindings_file", lambda: mapping)
    monkeypatch.setattr(cloud_windows_connector, "_current_authorization", lambda _p: True)
    registered = registered_project()
    selected = SimpleNamespace(directory=base, filename_stem="Registered")
    assert scoped.save(registered, TEST, test_file)
    target = resolve_owner_write_project(registered, selected, TEST)

    class NativeStage:
        calls: list[str] = []

        def begin(self) -> bool:
            self.calls.append("begin")
            return True

        def stage(self) -> None:
            self.calls.append("stage")
            if revocation == "remove_binding":
                scoped_store.pop(
                    (scoped._slot(scoped._identity(registered, TEST)), "secondary_project")
                )
            else:
                identity = scoped._identity(registered, TEST)
                scoped_store[(scoped._slot(identity), "secondary_project")] = json.dumps(
                    {**identity, "file": str(alternative_file)}
                ).encode()

        def commit(self) -> bool:
            self.calls.append("commit")
            return True

        def discard(self) -> bool:
            self.calls.append("discard")
            return True

    native = NativeStage()

    def current() -> bool:
        return _approved_write_target(registered, selected, TEST, target)

    assert current()
    expected_board_hash = hashlib.sha256(original).hexdigest()
    with pytest.raises(LocalWriteDeniedError, match="request denied"):
        run_offline_guarded_native_write(
            target,
            expected_board_hash,
            authorized=current,
            cancelled=lambda: not current(),
            native=native,
        )
    assert native.calls == ["begin", "stage", "discard"]
    assert board.read_bytes() == original
