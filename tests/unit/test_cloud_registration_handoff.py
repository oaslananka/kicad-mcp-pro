"""Owner-initiated Cloud migration: tests only in disposable private directories."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)
from typer.testing import CliRunner

from kicad_mcp import cloud_registration_handoff as handoff
from kicad_mcp import cloud_user_cli
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.server import app

pytestmark = pytest.mark.skipif(os.name != "posix", reason="Owner-private POSIX file transitions")

OLD_DEVICE = "11111111-1111-4111-8111-111111111111"
OLD_PROJECT = "22222222-2222-4222-8222-222222222222"
NEW_DEVICE = "33333333-3333-4333-8333-333333333333"
NEW_PROJECT = "44444444-4444-4444-8444-444444444444"
ORIGIN = "https://cloud.example.test"


def setup(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    root = tmp_path / "private-registry"
    root.mkdir(mode=0o700)
    (root / "projects").mkdir(mode=0o700)
    (root / "keys").mkdir(mode=0o700)
    folder = tmp_path / "existing-project"
    folder.mkdir()
    (folder / "sample.kicad_pcb").write_text("fixture", encoding="utf8")
    (folder / "sample.kicad_sch").write_text("fixture", encoding="utf8")
    oldkey = root / "keys" / (OLD_DEVICE + ".pem")
    oldkey.write_text("legacy-private-fixture", encoding="utf8")
    oldkey.chmod(0o600)
    newkey = root / "keys" / (NEW_DEVICE + ".pem")
    secret = Ed25519PrivateKey.generate()
    newkey.write_bytes(secret.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    newkey.chmod(0o600)
    pub = secret.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    bound = newkey.with_name(newkey.name + ".cloud-binding-v1.json")
    bound.write_text(
        json.dumps(
            {
                "origin": ORIGIN,
                "deviceId": NEW_DEVICE,
                "fingerprint": hashlib.sha256(pub).hexdigest(),
            }
        ),
        encoding="utf8",
    )
    bound.chmod(0o600)
    previous = root / "projects" / (OLD_PROJECT + ".json")
    previous.write_text(
        json.dumps(
            {
                "ownerSub": "legacy-owner",
                "cloudOrigin": ORIGIN,
                "deviceId": OLD_DEVICE,
                "projectId": OLD_PROJECT,
                "keySlot": OLD_DEVICE,
                "directory": str(folder),
                "filenameStem": "sample",
            }
        ),
        encoding="utf8",
    )
    previous.chmod(0o600)
    return root, previous, newkey, bound


def plan(root: Path) -> handoff.RegistrationHandoff:
    return handoff.prepare_handoff(
        root, owner_sub="current-owner", device_id=NEW_DEVICE, project_id=NEW_PROJECT
    )


def test_preflight_does_not_modify_registration(tmp_path: Path) -> None:
    root, previous, key, bound = setup(tmp_path)
    old = previous.read_bytes()
    preflight = plan(root)
    assert preflight.updated()["keySlot"] == NEW_DEVICE
    assert preflight.updated()["directory"] == preflight.old()["directory"]
    assert previous.read_bytes() == old
    assert not (root / "archived-project-registrations").exists()
    assert key.exists() and bound.exists()


def test_approved_handoff_archives_old_and_installs_one_private_record(tmp_path: Path) -> None:
    root, previous, key, bound = setup(tmp_path)
    old = previous.read_bytes()
    preflight = plan(root)
    handoff.activate_handoff(preflight)
    archived = root / "archived-project-registrations" / previous.name
    new = root / "projects" / (NEW_PROJECT + ".json")
    assert archived.read_bytes() == old
    assert stat.S_IMODE(archived.stat().st_mode) == 0o600
    assert stat.S_IMODE(archived.parent.stat().st_mode) == 0o700
    assert len(list((root / "projects").iterdir())) == 1
    assert json.loads(new.read_text()) == preflight.updated()
    assert stat.S_IMODE(new.stat().st_mode) == 0o600
    assert key.exists() and bound.exists()
    assert (root / "keys" / (OLD_DEVICE + ".pem")).exists()
    with pytest.raises(LocalApprovalDeniedError):
        handoff.activate_handoff(preflight)  # Cannot repeat or archive twice


@pytest.mark.parametrize(
    "fault",
    [
        "enabled",
        "wrong_device",
        "wrong_owner",
        "same_project",
        "bad_key",
        "public_binding",
        "symlink_binding",
        "collision",
    ],
)
def test_tampered_handoff_denied_without_mutation(tmp_path: Path, fault: str) -> None:
    root, previous, key, bound = setup(tmp_path)
    if fault == "enabled":
        (root / "connector-enabled.json").write_text("{}", encoding="utf8")
    elif fault == "bad_key":
        key.write_bytes(
            Ed25519PrivateKey.generate().private_bytes(
                Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
            )
        )
    elif fault == "public_binding":
        bound.chmod(0o644)
    elif fault == "symlink_binding":
        original = tmp_path / "binding.json"
        bound.rename(original)
        bound.symlink_to(original)
    elif fault == "collision":
        (root / "projects" / (NEW_PROJECT + ".json")).write_text("occupied", encoding="utf8")
    kwargs = {"owner_sub": "current-owner", "device_id": NEW_DEVICE, "project_id": NEW_PROJECT}
    if fault == "wrong_device":
        kwargs["device_id"] = "55555555-5555-4555-8555-555555555555"
    if fault == "wrong_owner":
        kwargs["owner_sub"] = ""
    if fault == "same_project":
        kwargs["project_id"] = OLD_PROJECT
    old = previous.read_bytes()
    with pytest.raises(LocalApprovalDeniedError):
        handoff.prepare_handoff(root, **kwargs)
    assert previous.read_bytes() == old
    assert not (root / "archived-project-registrations").exists()


def test_link_failure_recovers_old_record_without_leaking_tmp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, old, _key, _bound = setup(tmp_path)
    preflight = plan(root)
    old_bytes = old.read_bytes()
    monkeypatch.setattr(
        handoff.os, "link", lambda *a, **kw: (_ for _ in ()).throw(OSError("injected"))
    )
    with pytest.raises(LocalApprovalDeniedError):
        handoff.activate_handoff(preflight)
    assert old.read_bytes() == old_bytes
    assert not (root / "archived-project-registrations" / old.name).exists()
    assert list((root / "projects").iterdir()) == [old]


def test_cli_denies_headless_without_reading_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: False)
    monkeypatch.setattr(
        handoff, "prepare_handoff", lambda *_a, **_kw: pytest.fail("no headless registry reads")
    )
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "register-project",
            "--owner-sub",
            "owner",
            "--device-id",
            NEW_DEVICE,
            "--project-id",
            NEW_PROJECT,
        ],
    )
    assert result.exit_code != 0


def test_cli_owner_cancel_has_no_changes(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, old, _key, _bound = setup(tmp_path)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(handoff, "default_registry_root", lambda: root)
    old_bytes = old.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "register-project",
            "--owner-sub",
            "current-owner",
            "--device-id",
            NEW_DEVICE,
            "--project-id",
            NEW_PROJECT,
        ],
        input="n\n",
    )
    assert result.exit_code != 0
    assert old.read_bytes() == old_bytes
    assert not (root / "archived-project-registrations").exists()


def test_cli_owner_accepts_with_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, old, _key, _bound = setup(tmp_path)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(handoff, "default_registry_root", lambda: root)
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "register-project",
            "--owner-sub",
            "current-owner",
            "--device-id",
            NEW_DEVICE,
            "--project-id",
            NEW_PROJECT,
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert "Connector remains Off" in result.output
    assert not old.exists()
    assert (root / "archived-project-registrations" / old.name).is_file()


def test_rechecks_state_after_owner_review(tmp_path: Path) -> None:
    root, old, _key, _bound = setup(tmp_path)
    preflight = plan(root)
    old_bytes = old.read_bytes()
    current = json.loads(old.read_text())
    current["filenameStem"] = "different"
    old.write_text(json.dumps(current), encoding="utf8")
    with pytest.raises(LocalApprovalDeniedError):
        handoff.activate_handoff(preflight)
    assert not (root / "archived-project-registrations").exists()
    assert old.read_bytes() != old_bytes
    assert not (root / "projects" / (NEW_PROJECT + ".json")).exists()


@pytest.mark.parametrize(
    "fault", ["legacy_symlink", "archive_collision", "archive_symlink", "bound_duplicate"]
)
def test_rejects_archive_and_binding_collisions(tmp_path: Path, fault: str) -> None:
    root, old, _key, _bound = setup(tmp_path)
    old_bytes = old.read_bytes()
    if fault == "legacy_symlink":
        copy = tmp_path / "old-record.json"
        old.rename(copy)
        old.symlink_to(copy)
    elif fault == "archive_collision":
        archive = root / "archived-project-registrations"
        archive.mkdir(mode=0o700)
        (archive / old.name).write_text("existing", encoding="utf8")
    elif fault == "archive_symlink":
        (root / "archived-project-registrations").symlink_to(
            root / "projects", target_is_directory=True
        )
    else:
        other_key = root / "keys" / "55555555-5555-4555-8555-555555555555.pem"
        key = Ed25519PrivateKey.generate()
        other_key.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        other_key.chmod(0o600)
        pub = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        bound = other_key.with_name(other_key.name + ".cloud-binding-v1.json")
        bound.write_text(
            json.dumps(
                {
                    "origin": ORIGIN,
                    "deviceId": NEW_DEVICE,
                    "fingerprint": hashlib.sha256(pub).hexdigest(),
                }
            ),
            encoding="utf8",
        )
        bound.chmod(0o600)
    with pytest.raises(LocalApprovalDeniedError):
        plan(root)
    if fault == "legacy_symlink":
        assert old.is_symlink()
    else:
        assert old.read_bytes() == old_bytes
    assert not (root / "projects" / (NEW_PROJECT + ".json")).exists()


def test_existing_private_archive_directory_supported(tmp_path: Path) -> None:
    root, old, _key, _bound = setup(tmp_path)
    (root / "archived-project-registrations").mkdir(mode=0o700)
    handoff.activate_handoff(plan(root))
    assert (root / "archived-project-registrations" / old.name).is_file()


def test_post_install_validation_failure_restores_legacy_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, old, _key, _bound = setup(tmp_path)
    before = old.read_bytes()
    original = handoff._single_registered_identity
    calls = 0

    def inspect(registry: Path) -> dict[str, str]:
        nonlocal calls
        calls += 1
        # One call in revalidation, second after the new record is linked.
        if calls >= 2:
            raise LocalApprovalDeniedError("injected validation failure")
        return original(registry)

    preflight = plan(root)
    monkeypatch.setattr(handoff, "_single_registered_identity", inspect)
    with pytest.raises(LocalApprovalDeniedError):
        handoff.activate_handoff(preflight)
    assert old.read_bytes() == before
    assert len(list((root / "projects").iterdir())) == 1
    assert not (root / "archived-project-registrations" / old.name).exists()


def test_reused_key_slot_denied_even_when_new_device_id_differs(tmp_path: Path) -> None:
    root, old, _key, _bound = setup(tmp_path)
    previous = json.loads(old.read_text())
    previous["keySlot"] = NEW_DEVICE
    old.write_text(json.dumps(previous), encoding="utf8")
    with pytest.raises(LocalApprovalDeniedError):
        plan(root)
    assert old.is_file()


def test_cli_preflight_error_is_safe_and_preserves_old_registration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, old, _key, binding = setup(tmp_path)
    binding.chmod(0o644)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(handoff, "default_registry_root", lambda: root)
    old_bytes = old.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "register-project",
            "--owner-sub",
            "current-owner",
            "--device-id",
            NEW_DEVICE,
            "--project-id",
            NEW_PROJECT,
        ],
    )
    assert result.exit_code != 0
    assert "could not be verified" in result.output
    assert old.read_bytes() == old_bytes


def test_cli_failed_activation_reports_error_without_claiming_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root, old, _key, _bound = setup(tmp_path)
    monkeypatch.setattr(cloud_user_cli, "_owner_terminal", lambda: True)
    monkeypatch.setattr(handoff, "default_registry_root", lambda: root)
    monkeypatch.setattr(
        handoff,
        "activate_handoff",
        lambda *_a: (_ for _ in ()).throw(LocalApprovalDeniedError("synthetic failure")),
    )
    old_bytes = old.read_bytes()
    result = CliRunner().invoke(
        app,
        [
            "cloud",
            "register-project",
            "--owner-sub",
            "current-owner",
            "--device-id",
            NEW_DEVICE,
            "--project-id",
            NEW_PROJECT,
        ],
        input="y\n",
    )
    assert result.exit_code != 0
    assert "Local registration update failed" in result.output
    assert "Connector remains Off" not in result.output
    assert old.read_bytes() == old_bytes
