"""An independently pinned signer and server-observed trace are required."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import sys
from datetime import datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from kicad_mcp.evals import reference_ops_signed_witness, reference_ops_trace_validation
from kicad_mcp.evals.reference_ops_signed_witness import (
    SignedOpsWitnessError,
    reconcile_signed_ops_witness,
)
from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace

_ATTEMPT = "smoke-signed-test-v1"
_SERVER = "kicad-msi-signed-trace-v37"
_NONCE = "a" * 32


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple:
    root = tmp_path / ".dev-tools/reference-agent-runs"
    folder = root / _ATTEMPT
    folder.mkdir(parents=True, mode=0o700)
    folder.chmod(0o700)
    monkeypatch.setattr(reference_ops_trace_validation, "_TRACE_ROOT", root)
    monkeypatch.setattr(reference_ops_signed_witness, "_TRACE_ROOT", root)
    server = folder / "ops-mcp-trace.jsonl"

    async def make_trace() -> None:
        trace = ReferenceOpsTrace(path=server, attempt_id=_ATTEMPT)
        try:
            request = await trace.emit(
                event_type="tool_call", name="kicad_get_version", status="started"
            )
            await trace.emit(
                event_type="tool_result",
                name="kicad_get_version",
                status="completed",
                request_id=request,
            )
        finally:
            trace.close()

    asyncio.run(make_trace())
    records = [json.loads(line) for line in server.read_text().splitlines()]
    start = round(
        datetime.fromisoformat(records[0]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    )
    finish = round(
        datetime.fromisoformat(records[1]["timestamp"].replace("Z", "+00:00")).timestamp() * 1000
    )
    private_key = Ed25519PrivateKey.generate()
    public = private_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    import hashlib

    key_id = hashlib.sha256(public).hexdigest()
    payload = {
        "schema": "ops-mcp-witness.v1",
        "nonce": _NONCE,
        "target": f"pc.msi.mcp.{_SERVER}",
        "binding": "b" * 64,
        "startedAt": start - 500,
        "endedAt": finish + 500,
        "events": [
            {
                "id": 3,
                "phase": "call",
                "callId": "c" * 32,
                "tool": f"pc.msi.mcp.{_SERVER}.kicad_get_version",
                "at": start,
                "status": "pending",
                "durationMs": 0,
            },
            {
                "id": 4,
                "phase": "result",
                "callId": "c" * 32,
                "tool": f"pc.msi.mcp.{_SERVER}.kicad_get_version",
                "at": finish,
                "status": "ok",
                "durationMs": max(0, finish - start),
            },
        ],
        "complete": True,
        "keyId": key_id,
    }
    gateway = folder / "signed-gateway-witness.json"

    def sign(value):
        raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode()
        signature = base64.urlsafe_b64encode(private_key.sign(raw)).rstrip(b"=").decode()
        gateway.write_text(json.dumps({**value, "signature": signature}) + "\n")
        gateway.chmod(0o600)

    sign(payload)
    return server, gateway, base64.b64encode(public).decode(), key_id, payload, sign


def reconcile(evidence, **kw: object) -> reference_ops_signed_witness.SignedOpsWitnessSummary:
    server, gateway, public, kid, *_ = evidence
    options = {
        "attempt_id": _ATTEMPT,
        "phase_name": "schematic",
        "server_name": _SERVER,
        "nonce": _NONCE,
        "trusted_public_key_spki": public,
        "trusted_key_id": kid,
        **kw,
    }
    return reconcile_signed_ops_witness(server, gateway, **options)


def test_independent_signed_witness_matches_actual_server_trace(evidence) -> None:
    result = reconcile(evidence)
    assert result.status == "signed_gateway_server_matched_non_scored"
    assert result.tool_calls == 1
    assert result.counts_as_task_success is False
    assert result.gateway_log_digest.startswith("sha256:")
    assert result.server_log_digest.startswith("sha256:")


@pytest.mark.parametrize(
    "mutation",
    [
        "modified-status",
        "wrong-nonce",
        "wrong-server",
        "extra-field",
        "missing-pair",
        "duplicate-call",
        "bad-order",
        "fake-binding",
        "time-skew",
        "negative-duration",
        "unsigned",
        "wrong-key-id",
        "unknown-status",
        "empty-run",
        "bool-event-id",
        "future-time",
        "wrong-tool",
        "non-hex-call-id",
        "overlap",
        "duplicate-keys",
    ],
)
def test_signed_contract_rejects_malicious_or_mismatched_evidence(evidence, mutation) -> None:
    server, gateway, public, kid, original, sign = evidence
    payload = copy.deepcopy(original)
    if mutation == "modified-status":
        payload["events"][1]["status"] = "refused"
    elif mutation == "wrong-nonce":
        payload["nonce"] = "d" * 32
    elif mutation == "wrong-server":
        payload["target"] = "pc.msi.mcp.kicad-other"
    elif mutation == "extra-field":
        payload["rawOAuthToken"] = "PRIVATE"
    elif mutation == "missing-pair":
        payload["events"].pop()
    elif mutation == "duplicate-call":
        payload["events"][1] = copy.deepcopy(payload["events"][0])
    elif mutation == "bad-order":
        payload["events"] = list(reversed(payload["events"]))
    elif mutation == "fake-binding":
        payload["binding"] = ""
    elif mutation == "time-skew":
        payload["events"][0]["at"] -= 60_000
    elif mutation == "negative-duration":
        payload["events"][1]["durationMs"] = -1
    elif mutation == "unsigned":
        gateway.write_text(json.dumps(payload))
        with pytest.raises(SignedOpsWitnessError):
            reconcile(evidence)
        return
    elif mutation == "wrong-key-id":
        payload["keyId"] = "0" * 64
    elif mutation == "unknown-status":
        payload["events"][1]["status"] = "fabricated"
    elif mutation == "empty-run":
        payload["events"] = []
    elif mutation == "bool-event-id":
        payload["events"][0]["id"] = True
    elif mutation == "future-time":
        payload["endedAt"] = payload["startedAt"] + 100 * 60_000
    elif mutation == "wrong-tool":
        payload["events"][1]["tool"] = "pc.msi.mcp.kicad-msi-signed-trace-v37.run_drc"
    elif mutation == "non-hex-call-id":
        payload["events"][1]["callId"] = "bad"
    elif mutation == "overlap":
        payload["events"][0]["id"] = 99
    elif mutation == "duplicate-keys":
        text = gateway.read_text().replace('"nonce": ', '"nonce": "f", "nonce": ', 1)
        gateway.write_text(text)
        with pytest.raises(SignedOpsWitnessError):
            reconcile(evidence)
        return
    sign(payload)
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence)


def test_unknown_signing_key_fails(evidence) -> None:
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence, trusted_public_key_spki="AAAA")


def test_wrong_independent_fingerprint_fails(evidence) -> None:
    server, gateway, public, kid, *_ = evidence
    with pytest.raises(SignedOpsWitnessError):
        reconcile_signed_ops_witness(
            server,
            gateway,
            attempt_id=_ATTEMPT,
            phase_name="schematic",
            server_name=_SERVER,
            nonce=_NONCE,
            trusted_public_key_spki=public,
            trusted_key_id="f" * 64,
        )


def test_consumed_nonce_replay_refused(evidence) -> None:
    server, gateway, public, kid, *_ = evidence
    first = reconcile(evidence, consume_nonce=True)
    assert first.tool_calls == 1
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence, consume_nonce=True)
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence)
    # A new reserved directory in the same checkout cannot reuse the nonce.
    other = server.parent.parent / "second-private-attempt"
    other.mkdir(mode=0o700)
    with pytest.raises(SignedOpsWitnessError):
        reference_ops_signed_witness._reject_replay(other, _NONCE)


def test_artifact_scope_and_symlinks_rejected(evidence, tmp_path) -> None:
    server, gateway, public, kid, *_ = evidence
    external = tmp_path / "outside.json"
    external.write_bytes(gateway.read_bytes())
    with pytest.raises(SignedOpsWitnessError):
        reconcile_signed_ops_witness(
            server,
            external,
            attempt_id=_ATTEMPT,
            phase_name="schematic",
            server_name=_SERVER,
            nonce=_NONCE,
            trusted_public_key_spki=public,
            trusted_key_id=kid,
        )
    gateway.rename(gateway.with_suffix(".bak"))
    gateway.symlink_to(gateway.with_suffix(".bak"))
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence)


def test_cli_reports_only_non_scored_success_and_replay_block(
    evidence,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from scripts import reconcile_reference_ops_signed_witness as cli

    server, gateway, public, kid, *_ = evidence
    argv = [
        "signed-verify",
        "--server-trace",
        str(server),
        "--signed-gateway-witness",
        str(gateway),
        "--attempt-id",
        _ATTEMPT,
        "--phase",
        "schematic",
        "--server-name",
        _SERVER,
        "--nonce",
        _NONCE,
        "--trusted-public-key-spki",
        public,
        "--trusted-key-id",
        kid,
        "--consume-nonce",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert cli.main() == 0
    success = json.loads(capsys.readouterr().out)
    assert success["status"] == "signed_gateway_server_matched_non_scored"
    assert success["counts_as_task_success"] is False
    assert cli.main() == 2
    failure = json.loads(capsys.readouterr().out)
    assert failure == {"status": "blocked", "counts_as_task_success": False}


def test_repeated_call_id_in_distinct_pairs_rejected(evidence) -> None:
    server, gateway, public, kid, original, sign = evidence
    payload = copy.deepcopy(original)
    next_call = copy.deepcopy(payload["events"][0])
    next_result = copy.deepcopy(payload["events"][1])
    next_call["id"] = 5
    next_result["id"] = 6
    next_call["at"] = payload["events"][1]["at"] + 1
    next_result["at"] = next_call["at"] + 1
    payload["endedAt"] = next_result["at"] + 100
    payload["events"].extend((next_call, next_result))
    sign(payload)
    with pytest.raises(SignedOpsWitnessError, match="duplicate Gateway call ID"):
        reconcile(evidence)


def test_signed_json_document_without_trailing_newline_is_valid(evidence) -> None:
    _server, gateway, *_ = evidence
    gateway.write_bytes(gateway.read_bytes().rstrip(b"\n"))
    assert reconcile(evidence).tool_calls == 1


@pytest.mark.parametrize("attempt_id", ["../outside", "/outside-absolute", ".", "..", "x/y", ""])
def test_attempt_id_path_escape_is_typed_block(evidence, attempt_id: str) -> None:
    server, gateway, public, kid, *_ = evidence
    with pytest.raises(SignedOpsWitnessError):
        reconcile_signed_ops_witness(
            server,
            gateway,
            attempt_id=attempt_id,
            phase_name="schematic",
            server_name=_SERVER,
            nonce=_NONCE,
            trusted_public_key_spki=public,
            trusted_key_id=kid,
        )


def test_nonce_ledger_win32_mode_fallback_preserves_symlink_guards(
    evidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server, gateway, public, kid, *_ = evidence
    root = server.parent.parent
    ledger = root / ".signed-witness-nonce-ledger"
    ledger.mkdir(mode=0o700)
    ledger.chmod(0o755)
    # Simulate Windows (without mutating global os.name or pathlib internals).
    monkeypatch.setattr(reference_ops_signed_witness, "_not_private", lambda path: False)
    assert reconcile(evidence, consume_nonce=True).tool_calls == 1
    assert (ledger / (_NONCE + ".json")).exists()
    with pytest.raises(SignedOpsWitnessError):
        reconcile(evidence)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("non-object", "unexpected signed witness schema"),
        ("non-object-event", "invalid witness event fields"),
        ("event-missing-field", "invalid witness event fields"),
        ("event-extra-field", "invalid witness event fields"),
        ("different-paired-tool", "Gateway/server tool ordering differs"),
        ("server-outcome-disagrees", "Gateway/server outcomes disagree"),
        ("server-clock-skew", "Gateway/server timestamps or duration differ"),
        ("gateway-server-count-mismatch", "Gateway/server tool-call counts disagree"),
    ],
)
def test_authenticated_adversarial_event_shapes_and_reconciliation(
    evidence,
    case: str,
    expected: str,
) -> None:
    """A valid Ed25519 signature does not make dishonest runtime claims valid."""
    _server, gateway, _pub, _kid, original, sign = evidence
    payload = copy.deepcopy(original)
    if case == "non-object":
        gateway.write_text("[]\n")
    elif case == "non-object-event":
        payload["events"][0] = "not-a-dictionary"
    elif case == "event-missing-field":
        payload["events"][0].pop("durationMs")
    elif case == "event-extra-field":
        payload["events"][0]["unexpected_field"] = "not permitted"
    elif case == "different-paired-tool":
        for event in payload["events"]:
            event["tool"] = f"pc.msi.mcp.{_SERVER}.lib_search_symbols"
    elif case == "server-outcome-disagrees":
        payload["events"][1]["status"] = "error"
    elif case == "server-clock-skew":
        # Keep internal Gateway event order and run envelope valid.
        for event in payload["events"]:
            event["at"] += 31_000
        payload["endedAt"] += 32_000
    elif case == "gateway-server-count-mismatch":
        follow_call, follow_result = copy.deepcopy(payload["events"])
        follow_call["id"] = 5
        follow_call["callId"] = "d" * 32
        follow_call["at"] = payload["events"][1]["at"] + 1
        follow_result["id"] = 6
        follow_result["callId"] = "d" * 32
        follow_result["at"] = follow_call["at"] + 1
        payload["endedAt"] = follow_result["at"] + 1
        payload["events"].extend([follow_call, follow_result])
    if case != "non-object":
        sign(payload)
    with pytest.raises(SignedOpsWitnessError, match=expected):
        reconcile(evidence)


def test_pinned_signer_rejects_wrong_key_alg_and_bad_sig_shape(evidence) -> None:
    """Independent key pin and Ed25519 signature encoding both fail closed."""
    import hashlib

    from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1, generate_private_key

    _server, _gateway, pub, kid, original, _sign = evidence
    verify = reference_ops_signed_witness._verify_signature
    with pytest.raises(SignedOpsWitnessError, match="pinned signing key"):
        verify({**original, "signature": "?" * 86}, pub, "not-hex")
    ec_public = (
        generate_private_key(SECP256R1())
        .public_key()
        .public_bytes(
            Encoding.DER,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )
    ec_public_b64 = base64.b64encode(ec_public).decode()
    ec_public_key_id = hashlib.sha256(ec_public).hexdigest()
    invalid_signature_payload = {**original, "signature": "A" * 86}
    with pytest.raises(SignedOpsWitnessError, match="invalid Gateway signature"):
        verify(invalid_signature_payload, ec_public_b64, ec_public_key_id)
    with pytest.raises(SignedOpsWitnessError, match="invalid Gateway signature"):
        verify({**original, "signature": "not-base64!"}, pub, kid)


def test_private_replay_registry_symlink_or_wrong_permissions_block(evidence) -> None:
    server, _gateway, *_ = evidence
    registry = server.parent.parent / ".signed-witness-nonce-ledger"
    registry.mkdir(mode=0o700)
    registry.chmod(0o755)
    if reference_ops_signed_witness.os.name != "nt":
        with pytest.raises(SignedOpsWitnessError, match="not private"):
            reconcile(evidence)
    registry.rmdir()
    outside = server.parent.parent / "outside-private"
    outside.mkdir(mode=0o700)
    registry.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SignedOpsWitnessError, match="symlinked"):
        reconcile(evidence)


def test_run_replay_marker_symlink_is_refused(evidence) -> None:
    server, _gateway, *_ = evidence
    marker = server.parent / "signed-witness-consumed.json"
    marker.symlink_to(server)
    with pytest.raises(SignedOpsWitnessError, match="symlink"):
        reconcile(evidence)


def test_nonce_registry_claim_errors_are_fail_closed(
    evidence,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed exclusive claim cannot be counted as a verified run."""
    from pathlib import Path

    server, _gateway, *_ = evidence
    registry = server.parent.parent / ".signed-witness-nonce-ledger"
    original_mkdir = Path.mkdir

    def refuse_global_dir(path: Path, *args: object, **kwargs: object) -> None:
        if path == registry:
            raise PermissionError("simulated registry IO error")
        original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", refuse_global_dir)
    with pytest.raises(SignedOpsWitnessError, match="cannot create private nonce registry"):
        reconcile(evidence, consume_nonce=True)


def test_exclusive_nonce_file_claim_refuses_collision(evidence) -> None:
    server, _gateway, *_ = evidence
    marker = server.parent / "signed-witness-consumed.json"
    marker.write_text("already claimed")
    with pytest.raises(SignedOpsWitnessError, match="cannot lock ledger"):
        reference_ops_signed_witness._write_exclusive_ledger(
            marker,
            _NONCE,
            "a" * 64,
        )


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (None, False),
        (False, False),
        (True, False),
        ("12", False),
        (type("IntSubclass", (int,), {})(1), False),
        (-1, False),
        (0, True),
        (4, True),
    ],
)
def test_witness_integer_validation_excludes_boolean_and_other_types(
    candidate: object,
    expected: bool,
) -> None:
    assert reference_ops_signed_witness._valid_int(candidate) is expected
