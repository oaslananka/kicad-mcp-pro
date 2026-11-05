"""Offline native transaction fence and cancellation/recovery negative tests."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_marker import LocalWriteMarker
from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof
from kicad_mcp.cloud_write_transaction_guard import (
    NativeWriteRecoveryError,
    run_offline_guarded_native_write,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
ORIGINAL = b"(kicad_pcb (version 20240108) (generator pcbnew))\n"
POSIX = pytest.mark.skipif(os.name != "posix", reason="POSIX flock/openat required")


class StubNative:
    def __init__(self, on_stage: Callable[[], None] | None = None) -> None:
        self.calls: list[str] = []
        self.begin_result: object = True
        self.commit_result = True
        self.discard_result = True
        self.fail_on: str | None = None
        self.on_stage = on_stage
        self.stage_result: object = None

    def begin(self) -> object:
        self.calls.append("begin")
        if self.fail_on == "begin":
            raise RuntimeError("begin acknowledgement lost")
        return self.begin_result

    def stage(self) -> object:
        self.calls.append("stage")
        if self.on_stage is not None:
            self.on_stage()
        if self.fail_on == "stage":
            raise RuntimeError("stage failed")
        return self.stage_result

    def commit(self) -> bool:
        self.calls.append("commit")
        if self.fail_on == "commit":
            raise RuntimeError("commit acknowledgement lost")
        return self.commit_result

    def discard(self) -> bool:
        self.calls.append("discard")
        if self.fail_on == "discard":
            raise RuntimeError("rollback acknowledgement lost")
        return self.discard_result


def approved(tmp_path: Path) -> tuple[OperatorProject, Path, str]:
    folder = tmp_path / "operator"
    folder.mkdir(mode=0o700)
    board = folder / "disposable.kicad_pcb"
    board.write_bytes(ORIGINAL)
    board.chmod(0o600)
    return (
        OperatorProject(DEVICE, PROJECT, folder, "disposable"),
        board,
        hashlib.sha256(ORIGINAL).hexdigest(),
    )


def run(
    policy: OperatorProject,
    expected: str,
    native: StubNative,
    *,
    authorized: Callable[[], bool] = lambda: True,
    cancelled: Callable[[], bool] = lambda: False,
) -> None:
    run_offline_guarded_native_write(
        policy,
        expected,
        authorized=authorized,
        cancelled=cancelled,
        native=native,
    )


def deny(action: Callable[[], None]) -> None:
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        action()


def uncertain(action: Callable[[], None]) -> None:
    with pytest.raises(NativeWriteRecoveryError, match="^native recovery required$"):
        action()


def test_untrusted_policy_and_nonposix_fail_closed(tmp_path: Path) -> None:
    policy, _, sha = approved(tmp_path)
    invalid = OperatorProject(DEVICE, PROJECT, Path("relative"), "../escape")
    native = StubNative()
    deny(lambda: run(invalid, sha, native))
    assert native.calls == []
    if os.name != "posix":
        deny(lambda: run(policy, sha, native))
        assert native.calls == []


@POSIX
def test_exact_board_is_rechecked_and_committed_only_after_fresh_grants(tmp_path: Path) -> None:
    policy, board, sha = approved(tmp_path)
    native = StubNative()
    checked: list[str] = []

    def authorized() -> bool:
        checked.append("owner-grant")
        return True

    run(policy, sha, native, authorized=authorized)
    assert native.calls == ["begin", "stage", "commit"]
    assert checked == ["owner-grant", "owner-grant"]
    assert board.read_bytes() == ORIGINAL
    lock = policy.directory / "disposable.cloud-write.lock"
    assert lock.is_file()
    assert lock.stat().st_mode & 0o077 == 0


@POSIX
@pytest.mark.parametrize("failure", ["revoked", "cancelled", "stale", "invalid"])
def test_expired_consent_cancel_or_stale_revision_never_stages(
    tmp_path: Path, failure: str
) -> None:
    policy, board, sha = approved(tmp_path)
    native = StubNative()
    expected = "" if failure == "invalid" else "0" * 64 if failure == "stale" else sha
    deny(
        lambda: run(
            policy,
            expected,
            native,
            authorized=lambda: failure != "revoked",
            cancelled=lambda: failure == "cancelled",
        )
    )
    assert native.calls == []
    assert board.read_bytes() == ORIGINAL


@POSIX
@pytest.mark.parametrize("failure", ["cancel", "revoke", "file_changed", "directory_swapped"])
def test_precommit_revocation_and_revision_race_discard_without_commit(
    tmp_path: Path, failure: str
) -> None:
    policy, board, sha = approved(tmp_path)
    seen: list[str] = []
    changes: list[str] = []

    def granted() -> bool:
        changes.append("grant-check")
        return not (failure == "revoke" and len(changes) > 1)

    def cancelled() -> bool:
        seen.append("cancel-check")
        return failure == "cancel" and len(seen) > 1

    def modify() -> None:
        if failure == "file_changed":
            board.write_bytes(ORIGINAL + b"external change")
        elif failure == "directory_swapped":
            policy.directory.rename(tmp_path / "moved")

    native = StubNative(on_stage=modify)
    deny(lambda: run(policy, sha, native, authorized=granted, cancelled=cancelled))
    assert native.calls == ["begin", "stage", "discard"]
    assert "commit" not in native.calls


@POSIX
def test_native_stage_failure_rolls_back_but_failed_rollback_requires_recovery(
    tmp_path: Path,
) -> None:
    policy, _, sha = approved(tmp_path)
    native = StubNative()
    native.fail_on = "stage"
    deny(lambda: run(policy, sha, native))
    assert native.calls == ["begin", "stage", "discard"]

    native = StubNative()
    native.fail_on = "discard"
    native.on_stage = lambda: (_ for _ in ()).throw(RuntimeError("native stage failed"))
    uncertain(lambda: run(policy, sha, native))
    assert native.calls == ["begin", "stage", "discard"]


@POSIX
@pytest.mark.parametrize("failure", ["false", "raise"])
def test_ambiguous_commit_does_not_discard_or_retry(tmp_path: Path, failure: str) -> None:
    policy, _, sha = approved(tmp_path)
    native = StubNative()
    if failure == "false":
        native.commit_result = False
    else:
        native.fail_on = "commit"
    uncertain(lambda: run(policy, sha, native))
    assert native.calls == ["begin", "stage", "commit"]


@POSIX
def test_ambiguous_begin_does_not_guess_native_transaction_state(tmp_path: Path) -> None:
    policy, _, sha = approved(tmp_path)
    native = StubNative()
    native.fail_on = "begin"
    uncertain(lambda: run(policy, sha, native))
    assert native.calls == ["begin"]
    native = StubNative()
    native.begin_result = False
    deny(lambda: run(policy, sha, native))
    assert native.calls == ["begin"]


@POSIX
def test_hostile_existing_lock_files_are_rejected(tmp_path: Path) -> None:
    policy, _, sha = approved(tmp_path)
    lock = policy.directory / "disposable.cloud-write.lock"
    outside = tmp_path / "elsewhere"
    outside.write_text("protected", encoding="utf-8")
    lock.symlink_to(outside)
    deny(lambda: run(policy, sha, StubNative()))
    assert outside.read_text(encoding="utf-8") == "protected"
    lock.unlink()
    lock.touch(mode=0o600)
    lock.chmod(0o666)
    deny(lambda: run(policy, sha, StubNative()))
    lock.chmod(0o600)
    link = policy.directory / "extra"
    os.link(lock, link)
    deny(lambda: run(policy, sha, StubNative()))
    link.unlink()
    lock.unlink()
    # A FIFO/device substitution must never block before fstat rejects it.
    os.mkfifo(lock)
    deny(lambda: run(policy, sha, StubNative()))


@POSIX
def test_active_other_process_lock_prevents_native_mutation(tmp_path: Path) -> None:
    import fcntl

    policy, _, sha = approved(tmp_path)
    lock_path = policy.directory / "disposable.cloud-write.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        native = StubNative()
        deny(lambda: run(policy, sha, native))
        assert native.calls == []
    finally:
        os.close(fd)

    native = StubNative()
    run(policy, sha, native)
    assert native.calls == ["begin", "stage", "commit"]


@POSIX
def test_signed_one_use_proof_precedes_locked_native_stage(tmp_path: Path) -> None:
    """Join existing offline proof, replay, SHA and transaction primitives."""
    policy, board, digest = approved(tmp_path)
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
    command = json.loads(fixture.read_bytes())
    command["command"]["expectedBoardSha256"] = digest
    payload = json.dumps(command, separators=(",", ":")).encode("utf-8")
    key = Ed25519PrivateKey.generate()

    def encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    proof = json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 1,
            "payload": encode(payload),
            "signature": encode(key.sign(b"kicad-cloud-signed-write-proposal-v1\x00" + payload)),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    binding = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        operations=frozenset({"pcb_move_footprint"}),
        session_id="33333333-3333-4333-8333-333333333333",
        session_expires_unix_ms=1_800_000_020_000,
    )
    marker_root = tmp_path / "one-use-markers"
    marker_root.mkdir(mode=0o700)
    markers = LocalWriteMarker(marker_root)

    def verify() -> dict[str, object]:
        return verify_offline_signed_write_proof(
            proof,
            trusted_issuer_key=key.public_key(),
            verified=binding,
            operator_project=policy,
            now_unix_ms=1_800_000_000_000,
            consume_once=markers.consume_once,
        )

    checked = verify()
    assert checked["command"] == command["command"]
    native = StubNative()
    run(policy, digest, native)
    assert native.calls == ["begin", "stage", "commit"]
    assert board.read_bytes() == ORIGINAL

    denied_native = StubNative()
    deny(lambda: verify())
    assert denied_native.calls == []


@POSIX
def test_unexpected_native_status_never_counts_as_commit_success(tmp_path: Path) -> None:
    policy, _, digest = approved(tmp_path)
    native = StubNative()
    native.begin_result = None
    uncertain(lambda: run(policy, digest, native))
    assert native.calls == ["begin"]
    native = StubNative()
    native.stage_result = False
    deny(lambda: run(policy, digest, native))
    assert native.calls == ["begin", "stage", "discard"]
