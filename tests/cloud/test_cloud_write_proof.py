"""Offline signed write proposal proofs: no Cloud socket or KiCad mutation."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Lock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError
from kicad_mcp.cloud_write_proof import verify_offline_signed_write_proof

NOW = 1_800_000_000_000
DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
KEY = Ed25519PrivateKey.generate()
OTHER_KEY = Ed25519PrivateKey.generate()
PUBLIC_KEY = KEY.public_key()
PREFIX = b"kicad-cloud-signed-write-proposal-v1\x00"
PREFIX_V2 = b"kicad-cloud-signed-write-proposal-v2\x00"
BINDING = VerifiedLocalBinding(
    device_id=DEVICE,
    project_id=PROJECT,
    operations=frozenset({"pcb_move_footprint"}),
    session_id=SESSION,
    session_expires_unix_ms=NOW + 20_000,
)
POLICY = OperatorProject(
    device_id=DEVICE,
    project_id=PROJECT,
    directory=Path("/no-project-is-accessed"),
    filename_stem="no-files",
)
GOLDEN = (
    Path(__file__).resolve().parents[1] / "fixtures" / "cloud_write_contract_v1.json"
).read_bytes()


def _encode(blob: bytes) -> str:
    return base64.urlsafe_b64encode(blob).rstrip(b"=").decode("ascii")


def _signed(payload: bytes = GOLDEN) -> bytes:
    return json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 1,
            "payload": _encode(payload),
            "signature": _encode(KEY.sign(PREFIX + payload)),
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _v2_payload() -> bytes:
    body = json.loads(GOLDEN)
    body["version"] = 2
    body["command"]["expectedLiveBoardSha256"] = "b" * 64
    return json.dumps(body, separators=(",", ":")).encode("utf-8")


def _signed_v2(payload: bytes | None = None) -> bytes:
    if payload is None:
        payload = _v2_payload()
    return json.dumps(
        {
            "kind": "connector.signed_write_proposal",
            "version": 2,
            "payload": _encode(payload),
            "signature": _encode(KEY.sign(PREFIX_V2 + payload)),
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _consume_once():
    seen: set[tuple[str, str]] = set()

    def reserve(session_id: str, request_id: str) -> bool:
        token = (session_id, request_id)
        if token in seen:
            return False
        seen.add(token)
        return True

    return reserve


def _verify(
    proof: object,
    *,
    public_key: Ed25519PublicKey = PUBLIC_KEY,
    binding: VerifiedLocalBinding = BINDING,
    policy: OperatorProject = POLICY,
    now: int = NOW,
    consume: Callable[[str, str], bool] | None = None,
):
    return verify_offline_signed_write_proof(
        proof,
        trusted_issuer_key=public_key,
        verified=binding,
        operator_project=policy,
        now_unix_ms=now,
        consume_once=consume if consume is not None else _consume_once(),
    )


def test_valid_signed_proposal_is_bound_to_one_session_and_reserved_once() -> None:
    raw = _signed()
    reserve = _consume_once()
    assert _verify(raw, consume=reserve) == json.loads(GOLDEN)
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        _verify(raw, consume=reserve)


def test_v2_proposal_signs_both_distinct_revisions_and_replay_id() -> None:
    signed = _signed_v2()
    reservations: list[tuple[str, str]] = []

    def reserve(session: str, request: str) -> bool:
        reservations.append((session, request))
        return len(reservations) == 1

    parsed = _verify(signed, consume=reserve)
    assert parsed["version"] == 2
    command = parsed["command"]
    assert command["expectedBoardSha256"] == "a" * 64
    assert command["expectedLiveBoardSha256"] == "b" * 64
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        _verify(signed, consume=reserve)
    assert len(reservations) == 2


@pytest.mark.parametrize(
    "attack",
    [
        "modify_only_live",
        "modify_disk",
        "downgrade_envelope",
        "upgrade_v1_envelope",
        "v1_signature_v2_payload",
        "v2_signature_v1_payload",
        "missing_live_even_when_resigned",
        "invalid_live_even_when_resigned",
        "mismatched_project_even_when_resigned",
    ],
)
def test_v2_signature_and_version_downgrade_are_rejected_before_replay(attack: str) -> None:
    frame = json.loads(_signed_v2())
    if attack == "modify_only_live":
        command = json.loads(_v2_payload())
        command["command"]["expectedLiveBoardSha256"] = "c" * 64
        frame["payload"] = _encode(json.dumps(command).encode())
    elif attack == "modify_disk":
        command = json.loads(_v2_payload())
        command["command"]["expectedBoardSha256"] = "c" * 64
        frame["payload"] = _encode(json.dumps(command).encode())
    elif attack == "downgrade_envelope":
        frame["version"] = 1
    elif attack == "upgrade_v1_envelope":
        frame = json.loads(_signed())
        frame["version"] = 2
    elif attack == "v1_signature_v2_payload":
        frame = json.loads(_signed(_v2_payload()))
    elif attack == "v2_signature_v1_payload":
        frame = json.loads(_signed_v2(GOLDEN))
    else:
        command = json.loads(_v2_payload())
        if attack == "missing_live_even_when_resigned":
            del command["command"]["expectedLiveBoardSha256"]
        elif attack == "invalid_live_even_when_resigned":
            command["command"]["expectedLiveBoardSha256"] = "not-a-sha256"
        else:
            command["projectId"] = DEVICE
        frame = json.loads(_signed_v2(json.dumps(command).encode()))
    calls: list[tuple[str, str]] = []
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        _verify(json.dumps(frame).encode(), consume=lambda a, b: (calls.append((a, b)), True)[1])
    assert calls == []


def test_v2_invalid_local_binding_never_reserves() -> None:
    calls: list[tuple[str, str]] = []
    with pytest.raises(LocalWriteDeniedError):
        _verify(
            _signed_v2(),
            binding=replace(BINDING, session_id=PROJECT),
            consume=lambda a, b: (calls.append((a, b)), True)[1],
        )
    assert calls == []


def test_untrusted_signature_never_reserves_request() -> None:
    raw = _signed()
    calls: list[tuple[str, str]] = []

    def reserve(session: str, request: str) -> bool:
        calls.append((session, request))
        return True

    untrusted_public_key = OTHER_KEY.public_key()
    with pytest.raises(LocalWriteDeniedError):
        _verify(raw, public_key=untrusted_public_key, consume=reserve)

    envelope = json.loads(raw)
    envelope["payload"] = _encode(GOLDEN.replace(b"42.5", b"42.6"))
    tampered = json.dumps(envelope).encode()
    with pytest.raises(LocalWriteDeniedError):
        _verify(tampered, consume=reserve)
    assert calls == []


@pytest.mark.parametrize(
    "override",
    [
        {"kind": "connector.authorized_read"},
        {"version": 2},
        {"signature": ""},
        {"signature": "!" * 86},
        {"signature": "A" * 86},
        {"signature": "A" * 87},
        {"signature": "AA"},
        {"payload": "!!"},
        {"payload": "A"},
        {"payload": "AB"},
        {"payload": "A" * 1400},
        {"payload": "AA"},
        {"extra": "/etc/passwd"},
    ],
)
def test_malformed_signed_envelopes_are_denied(override: dict[str, object]) -> None:
    envelope = json.loads(_signed())
    envelope.update(override)
    raw = json.dumps(envelope).encode()
    with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
        _verify(raw)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b"NaN",
        b"[]",
        b'{"kind":"connector.signed_write_proposal","kind":"connector.signed_write_proposal"}',
        b" " * 2049,
    ],
)
def test_unparseable_or_oversized_proof_is_denied(raw: bytes) -> None:
    with pytest.raises(LocalWriteDeniedError):
        _verify(raw)


@pytest.mark.parametrize(
    "change",
    [
        ("projectId", DEVICE),
        ("deviceId", PROJECT),
        ("sessionId", PROJECT),
        ("deadlineUnixMs", NOW),
        ("deadlineUnixMs", NOW + 10_001),
        ("requestId", "not-a-uuid"),
    ],
)
def test_valid_signature_cannot_override_local_scope(change: tuple[str, object]) -> None:
    changed = json.loads(GOLDEN)
    changed[change[0]] = change[1]
    signed = _signed(json.dumps(changed).encode())
    with pytest.raises(LocalWriteDeniedError):
        _verify(signed)


def test_duplicate_nested_fields_and_nonfinite_payload_are_denied_even_if_signed() -> None:
    duplicated = GOLDEN.replace(b'"xMm":', b'"xMm": 17, "xMm":')
    nan = GOLDEN.replace(b"42.5", b"NaN")
    for payload in (duplicated, nan):
        proof = _signed(payload)
        with pytest.raises(LocalWriteDeniedError):
            _verify(proof)


def test_device_grant_and_expiry_are_still_required_after_signature_check() -> None:
    raw = _signed()
    other_session = replace(BINDING, session_id=PROJECT)
    wrong_project = replace(POLICY, project_id=DEVICE)
    read_only = replace(BINDING, operations=frozenset())
    for bad_binding, bad_policy, clock in (
        (other_session, POLICY, NOW),
        (BINDING, wrong_project, NOW),
        (read_only, POLICY, NOW),
        (BINDING, POLICY, NOW + 1000),
    ):
        with pytest.raises(LocalWriteDeniedError):
            _verify(raw, binding=bad_binding, policy=bad_policy, now=clock)


def test_non_atomic_or_unavailable_replay_reservation_fails_closed() -> None:
    raw = _signed()

    def unavailable(_session: str, _request: str) -> bool:
        raise RuntimeError("secret backend failure")

    def refused(_session: str, _request: str) -> bool:
        return False

    for reserve in (unavailable, refused):
        with pytest.raises(LocalWriteDeniedError, match="^request denied$"):
            _verify(raw, consume=reserve)


def test_atomic_reservation_prevents_parallel_replay() -> None:
    raw = _signed()
    used: set[tuple[str, str]] = set()
    lock = Lock()

    def consume(session: str, request: str) -> bool:
        with lock:
            item = session, request
            if item in used:
                return False
            used.add(item)
            return True

    def attempt(_: int) -> bool:
        try:
            _verify(raw, consume=consume)
            return True
        except LocalWriteDeniedError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(attempt, range(12)))
    assert accepted.count(True) == 1


def test_no_execution_or_project_access_is_performed_by_verification(tmp_path: Path) -> None:
    target = tmp_path / "untouched.kicad_pcb"
    target.write_bytes(b"original bytes")
    policy = replace(POLICY, directory=tmp_path, filename_stem="untouched")
    assert _verify(_signed(), policy=policy)["requestId"] == REQUEST
    assert target.read_bytes() == b"original bytes"
