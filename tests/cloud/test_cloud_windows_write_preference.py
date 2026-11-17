"""Per-owner device/project write preference is explicit and revocable."""

from __future__ import annotations

import os

import pytest

from kicad_mcp import cloud_windows_write_preference as preference
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

WINDOWS = pytest.mark.skipif(os.name != "nt", reason="Windows owner credential store")
RECORD = "1" * 32
PROJECT = "22222222-2222-4222-8222-222222222222"
OTHER_PROJECT = "33333333-3333-4333-8333-333333333333"


@WINDOWS
def test_preference_is_off_until_owner_remembers_exact_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored: dict[tuple[str, str], bytes] = {}
    monkeypatch.setattr(
        preference, "read_credential", lambda record, part: stored.get((record, part))
    )

    def create(record: str, part: str, value: bytes) -> None:
        assert (record, part) not in stored
        stored[(record, part)] = value

    monkeypatch.setattr(preference, "create_credential", create)
    monkeypatch.setattr(
        preference,
        "delete_credential",
        lambda record, part: bool(stored.pop((record, part), None)),
    )

    assert not preference.owner_native_write_remembered(RECORD, PROJECT)
    preference.remember_owner_native_write(RECORD, PROJECT)
    assert preference.owner_native_write_remembered(RECORD, PROJECT)
    assert not preference.owner_native_write_remembered(RECORD, OTHER_PROJECT)
    preference.remember_owner_native_write(RECORD, PROJECT)  # Idempotent
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, OTHER_PROJECT)
    assert preference.forget_owner_native_write(RECORD, PROJECT)
    assert not preference.owner_native_write_remembered(RECORD, PROJECT)


@WINDOWS
def test_preference_rejects_invalid_identity_and_tampered_vault(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[str] = []
    monkeypatch.setattr(preference, "read_credential", lambda _record, _part: b"unknown-policy")
    monkeypatch.setattr(preference, "create_credential", lambda *_: writes.append("unsafe"))
    for record, project in [
        ("../another", PROJECT),
        (RECORD, "../../board"),
        (RECORD, "not-a-uuid"),
    ]:
        with pytest.raises(LocalWriteDeniedError):
            preference.remember_owner_native_write(record, project)
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, PROJECT)
    assert not preference.owner_native_write_remembered(RECORD, PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.forget_owner_native_write(RECORD, PROJECT)
    assert writes == []


def test_owner_vault_policy_with_portable_simulated_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise Windows-only policy branches in Linux patch-coverage CI."""
    from types import SimpleNamespace

    monkeypatch.setattr(preference, "os", SimpleNamespace(name="nt"))
    stored: dict[tuple[str, str], bytes] = {}
    monkeypatch.setattr(
        preference, "read_credential", lambda record, part: stored.get((record, part))
    )

    def create(record: str, part: str, value: bytes) -> None:
        assert (record, part) not in stored
        stored[(record, part)] = value

    monkeypatch.setattr(preference, "create_credential", create)
    monkeypatch.setattr(
        preference,
        "delete_credential",
        lambda record, part: bool(stored.pop((record, part), None)),
    )
    assert not preference.owner_native_write_remembered(RECORD, PROJECT)
    assert not preference.forget_owner_native_write(RECORD, PROJECT)
    preference.remember_owner_native_write(RECORD, PROJECT)
    preference.remember_owner_native_write(RECORD, PROJECT)
    assert preference.owner_native_write_remembered(RECORD, PROJECT)
    assert not preference.owner_native_write_remembered(RECORD, OTHER_PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, OTHER_PROJECT)
    assert preference.forget_owner_native_write(RECORD, PROJECT)
    assert not preference.owner_native_write_remembered(RECORD, PROJECT)

    stored[(RECORD, "write_preference")] = b"untrusted"
    assert not preference.owner_native_write_remembered(RECORD, PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.forget_owner_native_write(RECORD, PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write("invalid", PROJECT)
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, "invalid")


@pytest.mark.skipif(os.name == "nt", reason="non-Windows only")
def test_write_preference_is_not_a_posix_permission() -> None:
    with pytest.raises(LocalWriteDeniedError):
        preference.remember_owner_native_write(RECORD, PROJECT)
