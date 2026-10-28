"""Offline-only project identity resolution. Not a trusted owner issuer."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kicad_mcp.cloud_local_registry import resolve_registered_read
from kicad_mcp.cloud_once import LocalApprovalDeniedError

pytestmark = pytest.mark.skipif(os.name != "posix", reason="No secure no-follow Windows registry")
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
ORIGIN = "https://cloud.example"


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "kicad-mcp-cloud"
    keys = root / "keys"
    projects = root / "projects"
    keys.mkdir(parents=True, mode=0o700)
    projects.mkdir(mode=0o700)
    key = keys / f"{DEVICE}.pem"
    directory = tmp_path / "approved"
    directory.mkdir()
    key.write_text("synthetic placeholder, not real key")
    key.chmod(0o600)
    record = projects / f"{PROJECT}.json"
    record.write_text(
        json.dumps(
            {
                "ownerSub": "owner-1",
                "cloudOrigin": ORIGIN,
                "deviceId": DEVICE,
                "projectId": PROJECT,
                "keySlot": DEVICE,
                "directory": str(directory),
                "filenameStem": "Example",
            }
        )
    )
    record.chmod(0o600)
    return root, directory, record


def _resolve(root: Path, **changes: str):
    fields = {
        "owner_sub": "owner-1",
        "origin": ORIGIN,
        "device_id": DEVICE,
        "project_id": PROJECT,
        "registry_root": root,
    }
    fields.update(changes)
    return resolve_registered_read(**fields)


def test_registered_fixed_paths_only(tmp_path: Path) -> None:
    root, directory, _ = _fixture(tmp_path)
    found = _resolve(root)
    assert found.key_file == root / "keys" / f"{DEVICE}.pem"
    assert found.project_directory == directory
    assert found.filename_stem == "Example"
    for mismatch in [
        {"owner_sub": "other"},
        {"origin": "https://other.example"},
        {"device_id": "33333333-3333-4333-8333-333333333333"},
        {"project_id": "44444444-4444-4444-8444-444444444444"},
        {"project_id": "../../etc"},
    ]:
        with pytest.raises(LocalApprovalDeniedError):
            _resolve(root, **mismatch)


@pytest.mark.parametrize(
    "tamper",
    [
        "symlink",
        "hardlink",
        "world_readable",
        "directory_swap",
        "bad_key_slot",
        "duplicate",
        "traversal",
        "extra",
        "wrong_owner",
    ],
)
def test_registry_record_tampering_is_denied(tmp_path: Path, tamper: str) -> None:
    root, _directory, record = _fixture(tmp_path)
    if tamper == "symlink":
        other = tmp_path / "other.json"
        record.rename(other)
        record.symlink_to(other)
    elif tamper == "hardlink":
        os.link(record, tmp_path / "alias.json")
    elif tamper == "world_readable":
        record.chmod(0o644)
    elif tamper == "directory_swap":
        (root / "projects").rename(root / "saved")
        (root / "projects").symlink_to(root / "saved", target_is_directory=True)
    elif tamper == "duplicate":
        record.write_text('{"projectId":"one","projectId":"two"}')
    else:
        data = json.loads(record.read_text())
        if tamper == "traversal":
            data["directory"] = str(tmp_path / "approved" / ".." / "other")
        elif tamper == "extra":
            data["arbitrary"] = "/etc/passwd"
        elif tamper == "bad_key_slot":
            data["keySlot"] = "../outside.pem"
        elif tamper == "wrong_owner":
            data["ownerSub"] = "other"
        record.write_text(json.dumps(data))
    with pytest.raises(LocalApprovalDeniedError):
        _resolve(root)


def test_missing_root_and_group_writable_key_directory_deny(tmp_path: Path) -> None:
    with pytest.raises(LocalApprovalDeniedError):
        _resolve(tmp_path / "absent")
    root, _directory, _record = _fixture(tmp_path)
    (root / "keys").chmod(0o770)
    with pytest.raises(LocalApprovalDeniedError):
        _resolve(root)


def test_legacy_cli_path_flags_rejected_by_both_commands() -> None:
    from kicad_mcp import cloud_once, cloud_pair

    parser = cloud_once._parser()
    with pytest.raises(SystemExit) as read_error:
        parser.parse_args(
            [
                "--cloud-origin",
                ORIGIN,
                "--owner-sub",
                "owner-1",
                "--device-id",
                DEVICE,
                "--project-id",
                PROJECT,
                "--project-directory",
                "/etc",
                "--filename-stem",
                "etc",
                "--private-key-file",
                "/etc/private.pem",
                "--allow-once",
            ]
        )
    assert read_error.value.code == 2

    # Pairing rejects a path before creating a key or initiating HTTP.
    with pytest.raises(SystemExit) as pairing_error:
        cloud_pair.main(
            [
                "--cloud-origin",
                ORIGIN,
                "--alias",
                "Fixture",
                "--private-key-file",
                "/etc/private.pem",
                "--begin-pairing",
            ]
        )
    assert pairing_error.value.code == 2


def test_registered_local_key_fingerprint_is_bound_to_device(tmp_path: Path) -> None:
    """Use genuine synthetic Ed25519 material, never owner production keys."""
    import hashlib

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    from kicad_mcp import cloud_once, cloud_pair

    root, _directory, _record = _fixture(tmp_path)
    keyfile = root / "keys" / f"{DEVICE}.pem"
    keyfile.unlink()
    signing_key = cloud_pair._create_private_key(keyfile)
    der = signing_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    cloud_once._save_owner_binding(
        keyfile, origin=ORIGIN, device_id=DEVICE, fingerprint=hashlib.sha256(der).hexdigest()
    )
    profile = _resolve(root)
    actual_key = cloud_once._load_bound_owner_key(profile.key_file, ORIGIN, DEVICE)
    assert actual_key.public_key() == signing_key.public_key()
    with pytest.raises(LocalApprovalDeniedError):
        cloud_once._load_bound_owner_key(profile.key_file, "https://other.example", DEVICE)
    with pytest.raises(LocalApprovalDeniedError):
        cloud_once._load_bound_owner_key(
            profile.key_file, ORIGIN, "77777777-7777-4777-8777-777777777777"
        )
