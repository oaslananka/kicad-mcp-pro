"""One-command restarts recover a browser-repaired device, never a foreign marker."""

from __future__ import annotations

import hashlib
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_windows_connector as connector
from kicad_mcp import cloud_windows_credentials as credentials
from kicad_mcp import cloud_windows_device_bootstrap as boot
from kicad_mcp import cloud_windows_local_selection as local_selection
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice, WindowsRegisteredProject


@pytest.fixture
def repaired(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, object]:
    """Simulate authenticated old device + owner browser-repaired project."""
    old_key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    fresh_key = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    )
    old = WindowsEnrolledDevice(
        "a" * 32,
        "https://cloud.example",
        "owner",
        str(uuid4()),
        hashlib.sha256(old_key).hexdigest(),
    )
    new = WindowsEnrolledDevice(
        "b" * 32, old.origin, old.owner_sub, str(uuid4()), hashlib.sha256(fresh_key).hexdigest()
    )
    previous = WindowsRegisteredProject(
        registration_id="c" * 32,
        record_id=old.record_id,
        origin=old.origin,
        owner_sub=old.owner_sub,
        device_id=old.device_id,
        fingerprint=old.fingerprint,
        project_id=str(uuid4()),
        filename_stem="Test",
    )
    replacement = WindowsRegisteredProject(
        registration_id="d" * 32,
        record_id=new.record_id,
        origin=new.origin,
        owner_sub=new.owner_sub,
        device_id=new.device_id,
        fingerprint=new.fingerprint,
        project_id=str(uuid4()),
        filename_stem="Test",
    )
    archive = {
        "registrationId": previous.registration_id,
        "recordId": previous.record_id,
        "deviceId": previous.device_id,
        "projectId": previous.project_id,
    }
    store: dict[tuple[str, str], bytes] = {
        (replacement.registration_id, "archived_selected"): json.dumps(
            archive, sort_keys=True, separators=(",", ":")
        ).encode(),
    }
    monkeypatch.setattr(boot, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(boot, "owner_connector_instance", nullcontext)
    monkeypatch.setattr(
        boot,
        "inspect_local_binding",
        lambda **kwargs: SimpleNamespace(
            fingerprint=old.fingerprint if kwargs["record_id"] == old.record_id else new.fingerprint
        ),
    )
    monkeypatch.setattr(connector, "selected_project", lambda: replacement)

    def archived_project(marker: object) -> WindowsRegisteredProject:
        if marker != archive:
            raise LocalApprovalDeniedError("unverified repair marker")
        return previous

    monkeypatch.setattr(connector, "_load_project_from_marker", archived_project)
    monkeypatch.setattr(
        local_selection,
        "inspect_owner_selected_project",
        lambda project: SimpleNamespace(directory=tmp_path, filename_stem=project.filename_stem),
    )

    def create(record: str, part: str, data: bytes) -> None:
        if (record, part) in store:
            raise LocalApprovalDeniedError("credential already exists")
        store[(record, part)] = data

    def delete(record: str, part: str) -> bool:
        return store.pop((record, part), None) is not None

    for target in (boot, credentials):
        monkeypatch.setattr(target, "read_credential", lambda r, p: store.get((r, p)))
        monkeypatch.setattr(target, "create_credential", create)
        monkeypatch.setattr(target, "delete_credential", delete, raising=False)
    boot.remember_device(old)
    return {
        "old": old,
        "new": new,
        "previous": previous,
        "replacement": replacement,
        "store": store,
        "create": create,
    }


def test_repaired_device_migrates_only_after_owner_approved_repair(repaired) -> None:
    replacement = repaired["replacement"]
    old = repaired["old"]
    new = repaired["new"]
    store = repaired["store"]
    assert boot.selected_device() == old
    boot.remember_existing_project_device(replacement, allow_repair_migration=True)
    assert boot.selected_device() == new
    assert store[
        (replacement.registration_id, "archived_device_selected")
    ] == boot._device_marker_payload(old)
    # An already reconciled device is safe to start again, without another migration.
    boot.remember_existing_project_device(replacement)
    assert boot.selected_device() == new


def test_unapproved_migration_fails_closed(repaired) -> None:
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(repaired["replacement"])
    assert boot.selected_device() == repaired["old"]


def test_repair_without_archived_selection_does_not_change_device(repaired) -> None:
    replacement = repaired["replacement"]
    repaired["store"].pop((replacement.registration_id, "archived_selected"))
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(replacement, allow_repair_migration=True)
    assert boot.selected_device() == repaired["old"]


def test_foreign_repair_archive_is_rejected(repaired) -> None:
    replacement = repaired["replacement"]
    stored = repaired["store"]
    key = (replacement.registration_id, "archived_selected")
    archive = json.loads(stored[key])
    archive["deviceId"] = str(uuid4())
    stored[key] = json.dumps(archive).encode()
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(replacement, allow_repair_migration=True)
    assert boot.selected_device() == repaired["old"]


@pytest.mark.parametrize(
    ("field", "value"), [("owner_sub", "other-owner"), ("origin", "https://other.example")]
)
def test_different_owner_or_origin_never_migrates(
    repaired, monkeypatch: pytest.MonkeyPatch, field: str, value: str
) -> None:
    from dataclasses import replace

    foreign = replace(repaired["replacement"], **{field: value})
    monkeypatch.setattr(connector, "selected_project", lambda: foreign)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(foreign, allow_repair_migration=True)
    assert boot.selected_device() == repaired["old"]


def test_marker_creation_failure_restores_old_device(repaired, monkeypatch) -> None:
    old_create = repaired["create"]
    store = repaired["store"]
    marker_slot = (boot._DEVICE_SELECTION_SLOT, "selected")

    def fail_new_device(record: str, part: str, data: bytes) -> None:
        if (record, part) == marker_slot and data != boot._device_marker_payload(repaired["old"]):
            raise LocalApprovalDeniedError("simulated vault failure")
        old_create(record, part, data)

    monkeypatch.setattr(boot, "create_credential", fail_new_device)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(repaired["replacement"], allow_repair_migration=True)
    assert boot.selected_device() == repaired["old"]
    assert store[marker_slot] == boot._device_marker_payload(repaired["old"])


def test_active_foreign_connector_blocks_migration(repaired, monkeypatch) -> None:
    def refuse():
        raise LocalApprovalDeniedError("Connector already active")

    monkeypatch.setattr(boot, "owner_connector_instance", refuse)
    with pytest.raises(LocalApprovalDeniedError):
        boot.remember_existing_project_device(repaired["replacement"], allow_repair_migration=True)
    assert boot.selected_device() == repaired["old"]
