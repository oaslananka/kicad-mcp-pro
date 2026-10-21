"""Independently verify signed Ops Gateway metadata against native MCP server trace.

A valid result authenticates Gateway-observed OAuth-client/run metadata only.
It never claims a uniquely attested ChatGPT conversation or PCB task success.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key

from .reference_corpus import REFERENCE_IDENTIFIER_PATTERN, ReferenceAgentLogEvent
from .reference_ops_gateway_audit import (  # pyright: ignore[reportPrivateUsage]
    _MAX_DURATION_SKEW_MS,  # pyright: ignore[reportPrivateUsage]
    _VALID_SERVER_NAME,  # pyright: ignore[reportPrivateUsage]
)
from .reference_ops_reconciliation import _normalized_pairs  # pyright: ignore[reportPrivateUsage]
from .reference_ops_trace_validation import (  # pyright: ignore[reportPrivateUsage]
    _load_trace,  # pyright: ignore[reportPrivateUsage]
    validate_reference_ops_trace,
)

_TRACE_ROOT = Path(__file__).resolve().parents[3] / ".dev-tools/reference-agent-runs"
_GATEWAY_FILENAME: Final = "signed-gateway-witness.json"
_GLOBAL_CONSUMED_DIRECTORY = ".signed-witness-nonce-ledger"
_CONSUMED_FILENAME = "signed-witness-consumed.json"
_MAX_GATEWAY_BYTES = 2_000_000
_MAX_EVENTS = 1024
_MAX_CLOCK_SKEW_MS = 30_000
_MAX_RUN_MS = 90 * 60_000
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FIELDS = frozenset(
    {
        "schema",
        "nonce",
        "target",
        "binding",
        "startedAt",
        "endedAt",
        "events",
        "complete",
        "keyId",
        "signature",
    }
)
_EVENT_FIELDS = frozenset({"id", "phase", "callId", "tool", "at", "status", "durationMs"})


class SignedOpsWitnessError(ValueError):
    """Fail closed on malformed, untrusted, or replayed witness evidence."""


@dataclass(frozen=True, slots=True)
class SignedOpsWitnessSummary:
    status: str
    attempt_id: str
    phase: str
    nonce: str
    tool_calls: int
    failed_calls: int
    key_id: str
    gateway_log_digest: str
    server_log_digest: str
    counts_as_task_success: bool = False
    unique_chatgpt_conversation_attested: bool = False


def _unique_dict(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in pairs:
        if name in result:
            raise SignedOpsWitnessError("duplicate Gateway witness JSON key")
        result[name] = value
    return result


def _valid_int(value: object, minimum: int = 0) -> bool:
    # Signed JSON integers must be exactly Python int: reject bool and subclasses.
    if type(value) is not int:
        return False
    return int(value) >= minimum


def _header(payload: object, *, nonce: str, target: str, key_id: str) -> None:
    if not isinstance(payload, dict):
        raise SignedOpsWitnessError("unexpected signed witness schema")
    if set(cast(dict[str, object], payload).keys()) != set(_FIELDS):
        raise SignedOpsWitnessError("unexpected signed witness fields")
    payload = cast(dict[str, Any], payload)
    if (
        payload["schema"] != "ops-mcp-witness.v1"
        or payload["complete"] is not True
        or payload["nonce"] != nonce
        or payload["target"] != target
        or payload["keyId"] != key_id
        or not isinstance(payload["binding"], str)
        or not _HEX64.fullmatch(payload["binding"])
        or not _valid_int(payload["startedAt"])
        or not _valid_int(payload["endedAt"])
        or payload["endedAt"] < payload["startedAt"]
        or payload["endedAt"] - payload["startedAt"] > _MAX_RUN_MS
        or not isinstance(payload["signature"], str)
        or not isinstance(payload["events"], list)
        or not 2 <= len(cast(list[object], payload["events"])) <= _MAX_EVENTS
        or len(cast(list[object], payload["events"])) % 2
    ):
        raise SignedOpsWitnessError("signed witness scope or metadata mismatch")


def _verify_signature(payload: dict[str, Any], public_key: str, trusted_key_id: str) -> None:
    if not _HEX64.fullmatch(trusted_key_id):
        raise SignedOpsWitnessError("independently pinned signing key required")
    try:
        der = base64.b64decode(public_key, validate=True)
        if hashlib.sha256(der).hexdigest() != trusted_key_id:
            raise SignedOpsWitnessError("untrusted signing key fingerprint")
        key = load_der_public_key(der)
        if not isinstance(key, Ed25519PublicKey):
            raise SignedOpsWitnessError("signing key must be Ed25519")
        signature = payload["signature"]
        if not re.fullmatch(r"[A-Za-z0-9_-]{86}", signature):
            raise SignedOpsWitnessError("invalid Ed25519 signature encoding")
        raw_signature = base64.b64decode(
            signature.replace("-", "+").replace("_", "/") + "==",
            validate=True,
        )
        unsigned = {k: v for k, v in payload.items() if k != "signature"}
        # JS JSON.stringify owns the wire contract; preserve input insertion order.
        signed_bytes = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":")).encode()
        key.verify(raw_signature, signed_bytes)
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise SignedOpsWitnessError("invalid Gateway signature or trusted key") from exc


def _validated_witness_event(
    entry: object,
    *,
    target: str,
    previous_id: int,
    previous_time: int,
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise SignedOpsWitnessError("invalid witness event fields")
    if set(cast(dict[str, object], entry)) != set(_EVENT_FIELDS):
        raise SignedOpsWitnessError("invalid witness event fields")
    event = cast(dict[str, Any], entry)
    if (
        not _valid_int(event["id"])
        or not _valid_int(event["at"])
        or not _valid_int(event["durationMs"])
        or event["id"] <= previous_id
        or event["at"] < previous_time
        or event["at"] < start_time
        or event["at"] > end_time
        or not isinstance(event["callId"], str)
        or not _HEX32.fullmatch(event["callId"])
        or not isinstance(event["tool"], str)
        or not event["tool"].startswith(target + ".")
    ):
        raise SignedOpsWitnessError("invalid witness event order or scope")
    return event


def _pairs(payload: dict[str, Any], target: str) -> list[tuple[str, str, int, int, int]]:
    events = cast(list[object], payload["events"])
    result: list[tuple[str, str, int, int, int]] = []
    previous_id = -1
    previous_time = payload["startedAt"]
    seen_call_ids: set[str] = set()
    for first_raw, last_raw in zip(events[::2], events[1::2], strict=True):
        first = _validated_witness_event(
            first_raw,
            target=target,
            previous_id=previous_id,
            previous_time=previous_time,
            start_time=payload["startedAt"],
            end_time=payload["endedAt"],
        )
        last = _validated_witness_event(
            last_raw,
            target=target,
            previous_id=first["id"],
            previous_time=first["at"],
            start_time=payload["startedAt"],
            end_time=payload["endedAt"],
        )
        previous_id, previous_time = last["id"], last["at"]
        if (
            first["phase"] != "call"
            or first["status"] != "pending"
            or first["durationMs"] != 0
            or last["phase"] != "result"
            or last["status"] not in {"ok", "error"}
            or first["callId"] != last["callId"]
            or first["tool"] != last["tool"]
            or last["durationMs"] > _MAX_RUN_MS
        ):
            raise SignedOpsWitnessError("unpaired, unauthorized or incomplete witness")
        if first["callId"] in seen_call_ids:
            raise SignedOpsWitnessError("duplicate Gateway call ID")
        seen_call_ids.add(first["callId"])
        result.append(
            (
                first["tool"].removeprefix(target + "."),
                last["status"],
                first["at"],
                last["at"],
                last["durationMs"],
            )
        )
    return result


def _match_server(
    signed: list[tuple[str, str, int, int, int]],
    server_bytes: bytes,
    attempt_id: str,
) -> int:
    observed = _normalized_pairs(
        server_bytes,
        attempt_id=attempt_id,
        origin="server_observed_mcp",
    )
    server_events = [
        ReferenceAgentLogEvent.model_validate_json(raw) for raw in server_bytes.splitlines()
    ]
    calls = [event for event in server_events if event.event_type == "tool_call"]
    results = [event for event in server_events if event.event_type == "tool_result"]
    if len(signed) != len(observed) or len(calls) != len(signed) or len(results) != len(signed):
        raise SignedOpsWitnessError("Gateway/server tool-call counts disagree")
    failed = 0
    for row, call, terminal, (name, status) in zip(
        signed,
        calls,
        results,
        observed,
        strict=True,
    ):
        tool, outcome, start_ms, end_ms, duration_ms = row
        if tool != name or tool != call.name or terminal.name != name:
            raise SignedOpsWitnessError("Gateway/server tool ordering differs")
        if (outcome == "ok") != (status == "completed"):
            raise SignedOpsWitnessError("Gateway/server outcomes disagree")
        server_start = int(call.timestamp.timestamp() * 1000)
        server_end = int(terminal.timestamp.timestamp() * 1000)
        server_duration = server_end - server_start
        if (
            server_duration < 0
            or abs(start_ms - server_start) > _MAX_CLOCK_SKEW_MS
            or abs(end_ms - server_end) > _MAX_CLOCK_SKEW_MS
            or abs(duration_ms - server_duration) > _MAX_DURATION_SKEW_MS
        ):
            raise SignedOpsWitnessError("Gateway/server timestamps or duration differ")
        failed += outcome == "error"
    return failed


def _not_private(path: Path) -> bool:
    return os.name != "nt" and bool(path.stat().st_mode & 0o077)


def _reject_replay(directory: Path, nonce: str) -> None:
    global_ledger = directory.parent / _GLOBAL_CONSUMED_DIRECTORY
    if global_ledger.is_symlink():
        raise SignedOpsWitnessError("global nonce ledger cannot be symlinked")
    if global_ledger.exists():
        if not global_ledger.is_dir() or _not_private(global_ledger):
            raise SignedOpsWitnessError("global nonce ledger is not private")
        reused = global_ledger / (nonce + ".json")
        if reused.is_symlink() or reused.exists():
            raise SignedOpsWitnessError("nonce was already consumed in this checkout")
    for filename in (_CONSUMED_FILENAME, "consumed-nonces.json"):
        p = directory / filename
        if p.is_symlink():
            raise SignedOpsWitnessError("nonce ledger is a symlink")
        if p.exists():
            raise SignedOpsWitnessError("attempt directory already consumed")


def _write_exclusive_ledger(path: Path, nonce: str, gateway_digest: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as exc:
        raise SignedOpsWitnessError("nonce already consumed or cannot lock ledger") from exc
    # A write failure must still leave a non-reusable ledger; never unlink it.
    content = (
        json.dumps(
            {
                "schema": "signed-ops-witness-consumed.v1",
                "nonce": nonce,
                "gatewaySha256": gateway_digest,
            },
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _consume(directory: Path, nonce: str, gateway_digest: str) -> None:
    global_ledger = directory.parent / _GLOBAL_CONSUMED_DIRECTORY
    try:
        global_ledger.mkdir(mode=0o700, exist_ok=True)
    except OSError as exc:
        raise SignedOpsWitnessError("cannot create private nonce registry") from exc
    if global_ledger.is_symlink() or _not_private(global_ledger):
        raise SignedOpsWitnessError("global nonce registry is not private")
    # Claim across distinct attempt directories in this single checkout first.
    _write_exclusive_ledger(global_ledger / (nonce + ".json"), nonce, gateway_digest)
    _write_exclusive_ledger(directory / _CONSUMED_FILENAME, nonce, gateway_digest)


def reconcile_signed_ops_witness(
    server_path: Path,
    gateway_path: Path,
    *,
    attempt_id: str,
    phase_name: str,
    server_name: str,
    nonce: str,
    trusted_public_key_spki: str,
    trusted_key_id: str,
    consume_nonce: bool = False,
) -> SignedOpsWitnessSummary:
    """Verify two distinct observations with external signer pin and replay guard.

    consume_nonce=True atomically marks the evidence accepted in its private
    attempt directory. This never reserves a scored attempt or changes KPI.
    """
    if not _VALID_SERVER_NAME.fullmatch(server_name) or not _HEX32.fullmatch(nonce):
        raise SignedOpsWitnessError("invalid server scope or nonce")
    if not re.fullmatch(REFERENCE_IDENTIFIER_PATTERN, attempt_id) or attempt_id in {".", ".."}:
        raise SignedOpsWitnessError("invalid reference attempt identifier")
    directory = _TRACE_ROOT / attempt_id
    if (
        server_path != directory / "ops-mcp-trace.jsonl"
        or gateway_path != directory / _GATEWAY_FILENAME
    ):
        raise SignedOpsWitnessError("evidence files must be in reserved attempt directory")
    try:
        _reject_replay(directory, nonce)
        summary = validate_reference_ops_trace(
            server_path,
            attempt_id=attempt_id,
            phase_name=phase_name,
        )
        server_bytes = _load_trace(
            root=_TRACE_ROOT,
            attempt_id=attempt_id,
            filename="ops-mcp-trace.jsonl",
        )
        gateway_bytes = _load_trace(
            root=_TRACE_ROOT,
            attempt_id=attempt_id,
            filename=_GATEWAY_FILENAME,
        )
        if len(gateway_bytes) > _MAX_GATEWAY_BYTES:
            raise SignedOpsWitnessError("oversized Gateway witness")
        if hashlib.sha256(server_bytes).hexdigest() != summary.digest.removeprefix("sha256:"):
            raise SignedOpsWitnessError("server trace changed during validation")
        payload = json.loads(gateway_bytes, object_pairs_hook=_unique_dict)
        target = f"pc.msi.mcp.{server_name}"
        _header(payload, nonce=nonce, target=target, key_id=trusted_key_id)
        _verify_signature(payload, trusted_public_key_spki, trusted_key_id)
        signed = _pairs(payload, target)
        failed = _match_server(signed, server_bytes, attempt_id)
        gateway_digest = hashlib.sha256(gateway_bytes).hexdigest()
        if consume_nonce:
            _consume(directory, nonce, gateway_digest)
        return SignedOpsWitnessSummary(
            status="signed_gateway_server_matched_non_scored",
            attempt_id=attempt_id,
            phase=phase_name,
            nonce=nonce,
            tool_calls=len(signed),
            failed_calls=failed,
            key_id=trusted_key_id,
            gateway_log_digest="sha256:" + gateway_digest,
            server_log_digest=summary.digest,
        )
    except (OSError, TypeError, ValueError) as exc:
        if isinstance(exc, SignedOpsWitnessError):
            raise
        raise SignedOpsWitnessError("signed witness or server trace is invalid") from exc
