"""Retain only existing Cloud projects on this verified local device."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


@pytest.mark.parametrize(
    "state", ["active", "project_disabled", "project_missing", "unavailable", "unverified"]
)
def test_migration_checks_membership_and_never_reimports_completed_entry(
    tmp_path: Path, monkeypatch, state
) -> None:
    from kicad_mcp import cloud_legacy_project_migration as migration

    pid = str(uuid4())
    file = tmp_path / "board.kicad_pro"
    file.touch()
    calls = []
    migrated = {}
    receipts = set()
    monkeypatch.setattr(migration, "legacy_candidates", lambda: {pid: file})

    def diagnose(*args: object) -> str:
        calls.append(args[3])
        return state

    def save(project_id, chosen):
        migrated[project_id] = chosen
        return True

    monkeypatch.setattr("kicad_mcp.cloud_device_inventory_status.inspect_inventory", diagnose)
    options = dict(
        origin="https://cloud.example",
        owner="owner",
        device=str(uuid4()),
        primary=None,
        key=Ed25519PrivateKey.generate(),
        authorized=lambda: True,
        completed=lambda p: p in receipts,
        record_completed=receipts.add,
        save=save,
    )
    expected = state in {"active", "project_disabled"}
    assert migration.migrate(**options) == int(expected)
    assert migrated == ({pid: file} if expected else {})
    if expected:
        migrated.clear()
        assert migration.migrate(**options) == 0
        assert not migrated and calls == [pid]
    elif state == "project_missing":
        assert pid in receipts
    else:
        assert not receipts


def test_posix_cache_rejects_shared_writers_and_ambiguous_json(tmp_path, monkeypatch) -> None:
    import json
    import os

    from kicad_mcp import cloud_legacy_project_migration as migration

    if os.name != "posix":
        pytest.skip("POSIX ownership checks")
    folder = tmp_path / "connector"
    folder.mkdir(mode=0o700)
    file = tmp_path / "board.kicad_pro"
    file.touch()
    cache = folder / "folder-bindings.json"
    pid = str(uuid4())
    monkeypatch.setattr(migration, "default_bindings_file", lambda: cache)
    cache.write_text(json.dumps({pid: str(file)}))
    cache.chmod(0o644)
    assert migration.legacy_candidates() == {pid: file}
    cache.chmod(0o666)
    assert migration.legacy_candidates() == {}
    cache.chmod(0o600)
    cache.write_text(
        '{"' + pid + '":' + json.dumps(str(file)) + ',"' + pid + '":' + json.dumps(str(file)) + "}"
    )
    assert migration.legacy_candidates() == {}
    cache.unlink()
    cache.symlink_to(file)
    assert migration.legacy_candidates() == {}


def test_windows_migration_receipt_survives_binding_removal(tmp_path, monkeypatch) -> None:
    from kicad_mcp import cloud_windows_scoped_projects as scoped
    from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice
    from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

    device = WindowsEnrolledDevice("a" * 32, _KICAD_CLOUD_ORIGIN, "owner", str(uuid4()), "b" * 64)
    pid = str(uuid4())
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
    monkeypatch.setattr(
        "kicad_mcp.cloud_legacy_project_migration.legacy_candidates", lambda: {pid: file}
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_device_inventory_status.inspect_inventory", lambda *_: "active"
    )
    key = Ed25519PrivateKey.generate()
    assert scoped.migrate_legacy(device, key, lambda: True, None) == 1
    assert scoped.resolve(device, pid).directory == tmp_path
    slot = scoped._slot(scoped._identity(device, pid))
    store.pop((slot, "secondary_project"))
    assert scoped.migrate_legacy(device, key, lambda: True, None) == 0
    assert scoped.resolve(device, pid) is None


def test_posix_migration_receipt_survives_binding_removal(tmp_path, monkeypatch) -> None:
    import os

    from kicad_mcp import cloud_posix_project_bindings as scoped
    from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

    if os.name != "posix":
        pytest.skip("POSIX private registry")
    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    record = {
        "cloudOrigin": _KICAD_CLOUD_ORIGIN,
        "ownerSub": "owner",
        "deviceId": str(uuid4()),
        "keySlot": str(uuid4()),
        "projectId": "",
    }
    pid = str(uuid4())
    file = tmp_path / "board.kicad_pro"
    file.touch()
    monkeypatch.setattr(
        "kicad_mcp.cloud_legacy_project_migration.legacy_candidates", lambda: {pid: file}
    )
    monkeypatch.setattr(
        "kicad_mcp.cloud_device_inventory_status.inspect_inventory", lambda *_: "active"
    )
    key = Ed25519PrivateKey.generate()
    assert scoped.migrate_legacy(root, record, key, lambda: True) == 1
    assert scoped.resolve_secondary(root, record, pid).directory == tmp_path
    (scoped._folder(root, record) / (pid + ".json")).unlink()
    assert scoped.migrate_legacy(root, record, key, lambda: True) == 0
    assert scoped.resolve_secondary(root, record, pid) is None


@pytest.mark.parametrize("changed", ["authority", "path"])
def test_migration_rechecks_local_authority_after_inventory(tmp_path, monkeypatch, changed) -> None:
    from kicad_mcp import cloud_legacy_project_migration as migration

    pid = str(uuid4())
    file = tmp_path / "board.kicad_pro"
    file.touch()
    original = {pid: file}
    state = {"authorized": True}
    receipts = []
    monkeypatch.setattr(migration, "legacy_candidates", lambda: original.copy())

    def inspect(*_args: object) -> str:
        if changed == "authority":
            state["authorized"] = False
        else:
            original[pid] = tmp_path / "another.kicad_pro"
        return "active"

    monkeypatch.setattr("kicad_mcp.cloud_device_inventory_status.inspect_inventory", inspect)
    assert (
        migration.migrate(
            origin="https://cloud.example",
            owner="owner",
            device=str(uuid4()),
            primary=None,
            key=Ed25519PrivateKey.generate(),
            authorized=lambda: state["authorized"],
            completed=lambda _: False,
            record_completed=receipts.append,
            save=lambda *_: pytest.fail("unverified selection"),
        )
        == 0
    )
    assert not receipts


@pytest.mark.parametrize("fault", ["shared-parent", "hardlink", "empty", "not-object", "bad-entry"])
def test_legacy_cache_never_imports_untrusted_paths(tmp_path, monkeypatch, fault) -> None:
    import json
    import os

    from kicad_mcp import cloud_legacy_project_migration as migration

    if os.name != "posix":
        pytest.skip("POSIX private directory checks")
    folder = tmp_path / "connector"
    folder.mkdir(mode=0o700)
    file = tmp_path / "board.kicad_pro"
    file.touch()
    cache = folder / "folder-bindings.json"
    pid = str(uuid4())
    cache.write_text(json.dumps({pid: str(file)}))
    cache.chmod(0o600)
    monkeypatch.setattr(migration, "default_bindings_file", lambda: cache)
    if fault == "shared-parent":
        folder.chmod(0o777)
    elif fault == "hardlink":
        os.link(cache, folder / "other.json")
    elif fault == "empty":
        cache.write_bytes(b"")
    elif fault == "not-object":
        cache.write_text("[]")
    else:
        cache.write_text(json.dumps({pid: 42, "invalid-uuid": str(file)}))
    try:
        assert migration.legacy_candidates() == {}
    finally:
        folder.chmod(0o700)
