"""Secondary Windows projects must be scoped to the exact paired identity."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject


def test_explicit_secondary_binding_is_device_scoped(tmp_path: Path, monkeypatch) -> None:
    from kicad_mcp import cloud_windows_scoped_projects as scoped

    primary = WindowsRegisteredProject(
        "a" * 32,
        "b" * 32,
        "https://cloud.example",
        "owner",
        str(uuid4()),
        "c" * 64,
        str(uuid4()),
        "first",
    )
    pid = str(uuid4())
    board = tmp_path / "board"
    board.mkdir()
    file = board / "board.kicad_pro"
    file.write_text("{}")
    store = {}
    monkeypatch.setattr(scoped, "read_credential", lambda slot, part: store.get((slot, part)))

    def create(slot, part, data):
        assert (slot, part) not in store
        store[(slot, part)] = data

    monkeypatch.setattr(scoped, "create_credential", create)
    monkeypatch.setattr(
        scoped,
        "read_windows_project_presence",
        lambda directory, stem: {"projectPresent": (directory / (stem + ".kicad_pro")).is_file()},
    )
    assert scoped.resolve(primary, pid) is None
    assert scoped.save(primary, pid, file)
    assert scoped.save(primary, pid, file)
    assert scoped.resolve(primary, pid).directory == board
    assert scoped.resolve(replace(primary, record_id="d" * 32), pid) is None
    assert scoped.resolve(replace(primary, owner_sub="other"), pid) is None
    alternative = tmp_path / "alternative"
    alternative.mkdir()
    other = alternative / "board.kicad_pro"
    other.write_text("{}")
    assert not scoped.save(primary, pid, other)
    assert scoped.resolve(primary, pid).directory == board
    file.unlink()
    assert scoped.resolve(primary, pid) is None


def test_existing_targets_only_returns_exact_device_bindings(tmp_path: Path, monkeypatch) -> None:
    from kicad_mcp import cloud_windows_scoped_projects as scoped
    from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice

    primary = WindowsRegisteredProject(
        "a" * 32,
        "b" * 32,
        "https://cloud.example",
        "owner",
        str(uuid4()),
        "c" * 64,
        str(uuid4()),
        "first",
    )
    device = WindowsEnrolledDevice(
        primary.record_id, primary.origin, primary.owner_sub, primary.device_id, primary.fingerprint
    )
    file = tmp_path / "board.kicad_pro"
    file.touch()
    store = {}
    monkeypatch.setattr(scoped, "read_credential", lambda slot, part: store.get((slot, part)))
    monkeypatch.setattr(
        scoped, "create_credential", lambda slot, part, data: store.__setitem__((slot, part), data)
    )
    monkeypatch.setattr(
        scoped, "read_windows_project_presence", lambda *_: {"projectPresent": True}
    )
    pid = str(uuid4())
    foreign = replace(primary, owner_sub="foreign")
    assert scoped.save(primary, pid, file)
    assert scoped.save(foreign, str(uuid4()), file)
    monkeypatch.setattr(
        scoped,
        "list_secondary_slots",
        lambda prefix: [slot for slot, part in store if slot.startswith(prefix)],
    )
    assert [target.project_id for target in scoped.existing_targets(device)] == [pid]
