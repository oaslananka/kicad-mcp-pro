"""POSIX replacement preserves the old keys until an approved new identity exists."""

from __future__ import annotations

import hashlib
import os
import secrets
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp import cloud_pair, cloud_pair_keys, cloud_posix_recovery

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX private storage")
ORIGIN = "https://kicad-mcp-pro.oaslananka.dev"


@pytest.mark.parametrize("historical", [False, True])
@pytest.mark.parametrize("interrupt", [False, True])
@pytest.mark.parametrize("switch_crash", [None, "projects", "keys", "new-keys"])
def test_replacement_stage_resumes_same_approved_request(
    tmp_path, monkeypatch, interrupt, switch_crash, historical
) -> None:
    from kicad_mcp import cloud_posix_replacement as replacement

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    old = keys / f"{uuid4()}.pem"
    key = cloud_pair._load_or_create(old)
    fingerprint = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    old_id, new_id, challenge = str(uuid4()), str(uuid4()), str(uuid4())
    cloud_pair_keys._save_owner_binding(
        old, origin=ORIGIN, device_id=old_id, fingerprint=fingerprint, owner_sub="owner"
    )
    identity = cloud_posix_recovery.inspect_unbound_device(root, ORIGIN)
    before = {p.name: p.read_bytes() for p in keys.iterdir()}
    events = []
    requests = []

    def begin(origin, alias, path):
        events.append("challenge")
        new = cloud_pair._load_or_create(path)
        pin = hashlib.sha256(
            new.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
        ).hexdigest()
        cloud_pair_keys._write_private_json(
            path.parent,
            path.with_suffix(cloud_pair._CHALLENGE_SUFFIX).name,
            {
                "challenge": challenge,
                "code": "ABC123-DEF456",
                "secret": "a" * 43,
                "fingerprint": pin,
                "expiry": 9999999999999,
                "origin": origin,
            },
        )
        return "", challenge, "ABC123-DEF456", 300

    def wait(*args: object) -> None:
        events.append("approved")
        args[-1]()

    def redeem(target, endpoint, payload, status):
        assert endpoint.endswith("/redeem") and status == 200
        requests.append(payload.copy())
        assert payload["recovery"] == {"deviceId": old_id, "ownerSub": "owner"}
        if interrupt and len(requests) == 1:
            raise KeyboardInterrupt
        return {
            "deviceId": new_id,
            "deviceFingerprint": cloud_pair_keys._read_private_json(
                root / replacement._PENDING, "approved.json"
            )["fingerprint"],
            "ownerSub": "owner",
            **({"recoveryReceipt": True} if historical else {"enabled": True}),
        }

    monkeypatch.setattr(cloud_pair, "start_enrollment", begin)
    monkeypatch.setattr(cloud_pair, "_wait_for_owner_approval", wait)
    monkeypatch.setattr(cloud_pair, "_post", redeem)

    def approval(*_: object) -> None:
        events.append("browser")

    if interrupt:
        with pytest.raises(KeyboardInterrupt):
            replacement.prepare_replacement(root, identity, "PC", approval)
    result = replacement.prepare_replacement(root, identity, "PC", approval)
    assert result[1]["deviceId"] == new_id
    assert {p.name: p.read_bytes() for p in keys.iterdir()} == before
    assert events == ["challenge", "approved", "browser"]
    if interrupt:
        assert requests[0] == requests[1]
    assert not (root / "projects").exists()
    from kicad_mcp.cloud_posix_device_bootstrap import adopt_project

    board = tmp_path / "board"
    board.mkdir()
    file = board / "board.kicad_pro"
    file.write_text("{}")
    pid = str(uuid4())
    assert adopt_project(root, identity, pid, file)
    record = cloud_pair_keys._read_private_json(root / "projects", pid + ".json")
    original_move = replacement._move_directory

    def move(source, destination):
        original_move(source, destination)
        if switch_crash == "projects" and source == root / "projects":
            raise KeyboardInterrupt
        if switch_crash == "keys" and source == root / "keys":
            raise KeyboardInterrupt
        if switch_crash == "new-keys" and destination == root / "keys":
            raise KeyboardInterrupt

    monkeypatch.setattr(replacement, "_move_directory", move)
    if switch_crash is not None:
        with pytest.raises(KeyboardInterrupt):
            replacement.complete_replacement(root, identity, result, record)
        monkeypatch.setattr(replacement, "_move_directory", original_move)
        assert replacement.resume_switch(root, ORIGIN)
    else:
        replacement.complete_replacement(root, identity, result, record)
    assert not replacement.resume_switch(root, ORIGIN)
    current = cloud_posix_recovery.inspect_unbound_device(root, ORIGIN)
    assert current[1] == result[1]
    assert not cloud_posix_recovery._private_names(root / "projects")
    archive = root / ("replaced-" + old.stem) / "old"
    assert {p.name: p.read_bytes() for p in (archive / "keys").iterdir()} == before
    assert cloud_pair_keys._read_private_json(archive / "projects", pid + ".json") == record
    assert file.read_text() == "{}"
    assert not (root / ("replaced-" + old.stem) / "approved.json").exists()


@pytest.mark.parametrize(
    "state",
    ["active", "device_disabled", "unavailable", "project_missing", "unverified", "device_revoked"],
)
def test_diagnosis_only_replaces_removed_device(tmp_path, monkeypatch, state) -> None:
    from kicad_mcp import cloud_posix_replacement as replacement

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    identity = (root / "key.pem", {"origin": ORIGIN, "deviceId": str(uuid4()), "ownerSub": "owner"})
    monkeypatch.setattr(cloud_posix_recovery, "inspect_unbound_device", lambda *_: identity)
    monkeypatch.setattr("kicad_mcp.cloud_posix_device_bootstrap.read_project", lambda *_: None)
    monkeypatch.setattr("kicad_mcp.cloud_once._load_bound_owner_key", lambda *_: object())
    monkeypatch.setattr(
        "kicad_mcp.cloud_device_inventory_status.inspect_inventory", lambda *_: state
    )
    events = []
    monkeypatch.setattr(
        replacement, "prepare_replacement", lambda *_: events.append("prepare") or identity
    )
    monkeypatch.setattr(replacement, "complete_replacement", lambda *_: events.append("switch"))
    expected = state in {"unverified", "device_revoked"}
    assert replacement.recover_device(root, ORIGIN, "PC", lambda *_: None) == expected
    assert events == (["prepare", "switch"] if expected else [])


def test_definite_refusal_archives_staging_without_changing_old_identity(
    tmp_path, monkeypatch
) -> None:
    from kicad_mcp import cloud_posix_replacement as replacement
    from kicad_mcp.cloud_windows_enrollment import WindowsRecoveryDeniedError

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    old = keys / f"{uuid4()}.pem"
    key = cloud_pair._load_or_create(old)
    pin = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair_keys._save_owner_binding(
        old, origin=ORIGIN, device_id=str(uuid4()), fingerprint=pin, owner_sub="owner"
    )
    identity = cloud_posix_recovery.inspect_unbound_device(root, ORIGIN)
    monkeypatch.setattr(
        "kicad_mcp.cloud_device_inventory_status.inspect_inventory", lambda *_: "unverified"
    )

    def refuse(*_args: object):
        staged = replacement._validate_stage(root / replacement._PENDING, identity)
        cloud_pair._load_or_create(staged)
        cloud_pair_keys._write_private_json(
            staged.parent,
            staged.with_suffix(cloud_pair._CHALLENGE_SUFFIX).name,
            {"secret": secrets.token_urlsafe(32)},
        )
        cloud_pair_keys._write_private_json(
            staged.parent.parent, "approved.json", {"secret": secrets.token_urlsafe(32)}
        )
        raise WindowsRecoveryDeniedError("refused")

    monkeypatch.setattr(replacement, "prepare_replacement", refuse)
    with pytest.raises(ValueError, match="not approved"):
        replacement.recover_device(root, ORIGIN, "PC", lambda *_: None)
    assert not replacement.pending_replacement(root)
    assert cloud_posix_recovery.inspect_unbound_device(root, ORIGIN) == identity
    archives = list(root.glob("rejected-*"))
    assert len(archives) == 1
    assert not (archives[0] / "approved.json").exists()
    assert not list((archives[0] / "keys").glob("*.challenge.json"))


@pytest.mark.parametrize("fault", ["orphan", "foreign-journal", "foreign-file", "foreign-key"])
def test_replacement_stage_preserves_unrecognized_private_records(tmp_path, fault) -> None:
    from kicad_mcp import cloud_posix_replacement as replacement

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    old = keys / f"{uuid4()}.pem"
    key = cloud_pair._load_or_create(old)
    fingerprint = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair_keys._save_owner_binding(
        old, origin=ORIGIN, device_id=str(uuid4()), fingerprint=fingerprint, owner_sub="owner"
    )
    identity = cloud_posix_recovery.inspect_unbound_device(root, ORIGIN)
    stage = root / replacement._PENDING
    stage.mkdir(mode=0o700)
    if fault == "orphan":
        cloud_pair_keys._write_private_json(stage, "orphan.json", {})
    else:
        journal = {
            "previous": str(uuid4()) if fault == "foreign-journal" else old.stem,
            "binding": identity[1],
            "replacement": str(uuid4()),
        }
        cloud_pair_keys._write_private_json(stage, "request.json", journal)
        if fault == "foreign-file":
            cloud_pair_keys._write_private_json(stage, "foreign.json", {})
        elif fault == "foreign-key":
            pending_keys = stage / "keys"
            pending_keys.mkdir(mode=0o700)
            cloud_pair._load_or_create(pending_keys / f"{uuid4()}.pem")
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        replacement._validate_stage(stage, identity)
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before


@pytest.mark.parametrize(
    "fault",
    [
        "foreground",
        "invalid-journal",
        "wrong-owner",
        "changed-request",
        "archive-exists",
        "unexpected-project",
        "changed-binding",
        "missing-staged-key",
    ],
)
def test_resume_replacement_refuses_inconsistent_switch_before_moving_keys(tmp_path, fault) -> None:
    from kicad_mcp import cloud_posix_replacement as replacement
    from kicad_mcp.cloud_managed_connector import _FOREGROUND_FILE

    root = tmp_path / "registry"
    root.mkdir(mode=0o700)
    keys = root / "keys"
    keys.mkdir(mode=0o700)
    old = keys / f"{uuid4()}.pem"
    key = cloud_pair._load_or_create(old)
    pin = hashlib.sha256(
        key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair_keys._save_owner_binding(
        old, origin=ORIGIN, device_id=str(uuid4()), fingerprint=pin, owner_sub="owner"
    )
    identity = cloud_posix_recovery.inspect_unbound_device(root, ORIGIN)
    stage = root / replacement._PENDING
    new = replacement._validate_stage(stage, identity)
    new_key = cloud_pair._load_or_create(new)
    new_pin = hashlib.sha256(
        new_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    ).hexdigest()
    cloud_pair_keys._save_owner_binding(
        new,
        origin=ORIGIN,
        device_id=str(uuid4()),
        fingerprint=new_pin,
        owner_sub="foreign" if fault == "wrong-owner" else "owner",
    )
    new_identity = cloud_posix_recovery.inspect_unbound_device(stage, ORIGIN)
    journal = {
        "previous": old.stem,
        "oldBinding": identity[1],
        "replacement": new.stem,
        "newBinding": new_identity[1],
        "project": None,
    }
    cloud_pair_keys._write_private_json(
        stage, "switch.json", {} if fault == "invalid-journal" else journal
    )
    if fault == "foreground":
        cloud_pair_keys._write_private_json(root, _FOREGROUND_FILE, {})
    elif fault == "changed-request":
        cloud_pair_keys._write_private_json(stage, "request.json", {})
    elif fault == "archive-exists":
        (root / ("replaced-" + old.stem)).mkdir(mode=0o700)
    elif fault == "unexpected-project":
        projects = root / "projects"
        projects.mkdir(mode=0o700)
        cloud_pair_keys._write_private_json(projects, "unexpected.json", {})
    elif fault == "changed-binding":
        cloud_pair_keys._write_private_json(
            stage,
            "switch.json",
            {**journal, "newBinding": {**new_identity[1], "deviceId": str(uuid4())}},
        )
    elif fault == "missing-staged-key":
        import shutil

        shutil.rmtree(new.parent)
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        replacement.resume_switch(root, ORIGIN)
    assert {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    } == before
