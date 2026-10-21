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
