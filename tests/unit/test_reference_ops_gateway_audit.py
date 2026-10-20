"""Independent gateway audit metadata can match MCP traces, never attest success."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kicad_mcp.evals import reference_ops_gateway_audit, reference_ops_trace_validation
from kicad_mcp.evals.reference_ops_gateway_audit import (
    ReferenceOpsGatewayAuditError,
    reconcile_gateway_audit,
)
from kicad_mcp.evals.reference_ops_trace import ReferenceOpsTrace

_SERVER = "kicad-msi-schematic-e2e-20261020"
_ATTEMPT = "smoke-20261020-schematic"


@pytest.fixture
def evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / ".dev-tools/reference-agent-runs"
    folder = root / _ATTEMPT
    folder.mkdir(parents=True, mode=0o700)
    folder.chmod(0o700)
    monkeypatch.setattr(reference_ops_gateway_audit, "_TRACE_ROOT", root)
    monkeypatch.setattr(reference_ops_trace_validation, "_TRACE_ROOT", root)
    server = folder / "ops-mcp-trace.jsonl"

    async def create_trace() -> None:
        trace = ReferenceOpsTrace(path=server, attempt_id=_ATTEMPT)
        try:
            for name in ("kicad_get_version", "lib_search_symbols"):
                request_id = await trace.emit(event_type="tool_call", name=name, status="started")
                await trace.emit(
                    event_type="tool_result",
                    name=name,
                    status="completed",
                    request_id=request_id,
                )
        finally:
            trace.close()

    asyncio.run(create_trace())
    raw_events = [json.loads(line) for line in server.read_text().splitlines()]
    completed = [event for event in raw_events if event["event_type"] == "tool_result"]
    started = [event for event in raw_events if event["event_type"] == "tool_call"]
    rows = [
        {
            "id": 900 + i,
            "at": int(
                datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00")).timestamp()
            ),
            "tool": f"pc.msi.mcp.{_SERVER}.{call['name']}",
            "device": "msi",
            "status": "ok",
            "duration_ms": 25,
        }
        for i, (call, result) in enumerate(zip(started, completed, strict=True))
    ]
    payload = {
        "schema_version": "ops-gateway-audit-witness.v1",
        "source": "ops-gateway-sqlite-readonly",
        "observed_on": "vps",
        "device": "msi",
        "tool_prefix": f"pc.msi.mcp.{_SERVER}.",
        "capture_utc": datetime.now(UTC).isoformat(),
        "client_count": 1,
        "rows": rows,
    }
    witness = folder / "ops-gateway-audit.json"
    witness.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    witness.chmod(0o600)
    return server, witness


def _reconcile(paths: tuple[Path, Path], server_name: str = _SERVER):
    return reconcile_gateway_audit(
        paths[0],
        paths[1],
        attempt_id=_ATTEMPT,
        phase_name="schematic",
        server_name=server_name,
    )


def test_positive_match_is_never_authenticated_or_scored(
    evidence: tuple[Path, Path],
) -> None:
    result = _reconcile(evidence)
    assert result.tool_calls == 2
    assert (result.first_audit_id, result.last_audit_id) == (900, 901)
    assert result.status == "gateway_server_matched_unattested"
    assert result.counts_as_task_success is False
    assert result.server_log_digest.startswith("sha256:")
    assert result.gateway_log_digest.startswith("sha256:")


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong-tool",
        "duplicate-id",
        "wrong-device",
        "wrong-prefix",
        "two-clients",
        "unapproved-source",
        "wrong-observer",
        "transport-error",
        "large-clock-skew",
        "duration-mismatch",
        "extra-secret-field",
        "extra-client-identity",
        "missing-row",
        "extra-row",
        "missing-utc",
        "malformed-json",
        "non-object-row",
        "string-id",
        "bool-id",
    ],
)
def test_rejects_unreconciled_or_untrusted_gateway_witness(
    evidence: tuple[Path, Path], mutation: str
) -> None:
    witness = evidence[1]
    payload = json.loads(witness.read_text())
    rows = payload["rows"]
    if mutation == "wrong-tool":
        rows[0]["tool"] = rows[-1]["tool"]
    elif mutation == "duplicate-id":
        rows[-1]["id"] = rows[0]["id"]
    elif mutation == "wrong-device":
        rows[0]["device"] = "laptop"
    elif mutation == "wrong-prefix":
        payload["tool_prefix"] = "pc.msi.mcp.fake."
    elif mutation == "two-clients":
        payload["client_count"] = 2
    elif mutation == "unapproved-source":
        payload["source"] = "untrusted-user-generated"
    elif mutation == "wrong-observer":
        payload["observed_on"] = "msi"
    elif mutation == "transport-error":
        rows[0]["status"] = "error"
    elif mutation == "large-clock-skew":
        rows[0]["at"] += 400
        rows[1]["at"] += 400
    elif mutation == "duration-mismatch":
        rows[0]["duration_ms"] = 900000
    elif mutation == "extra-secret-field":
        rows[0]["api_key"] = "must-not-be-present"
    elif mutation == "extra-client-identity":
        payload["client_id"] = "must-not-be-present"
    elif mutation == "missing-row":
        rows.pop()
    elif mutation == "extra-row":
        rows.append({**rows[-1], "id": 999})
    elif mutation == "missing-utc":
        payload["capture_utc"] = "2026-10-20T02:00:00"
    elif mutation == "non-object-row":
        rows[0] = "invalid"
    elif mutation == "string-id":
        rows[0]["id"] = "900"
    elif mutation == "bool-id":
        rows[0]["id"] = True
    witness.write_text("{not json" if mutation == "malformed-json" else json.dumps(payload) + "\n")
    with pytest.raises(ReferenceOpsGatewayAuditError):
        _reconcile(evidence)


@pytest.mark.parametrize("mutation", ["symlink", "overly-permissive", "missing"])
def test_gateway_witness_private_path_is_required(
    evidence: tuple[Path, Path], mutation: str
) -> None:
    witness = evidence[1]
    if mutation == "symlink":
        target = witness.with_name("renamed-audit.json")
        witness.rename(target)
        try:
            witness.symlink_to(target)
        except OSError:
            pytest.skip("symlinks unsupported")
    elif mutation == "overly-permissive":
        if os.name == "nt":
            pytest.skip("POSIX permissions unavailable")
        witness.chmod(0o644)
    else:
        witness.unlink()
    with pytest.raises(ReferenceOpsGatewayAuditError):
        _reconcile(evidence)


def test_server_name_and_reserved_paths_are_not_user_selectable(
    evidence: tuple[Path, Path],
) -> None:
    with pytest.raises(ReferenceOpsGatewayAuditError):
        _reconcile(evidence, server_name="../../etc")
    other_path = evidence[1].with_name("audit-other.json")
    with pytest.raises(ReferenceOpsGatewayAuditError):
        reconcile_gateway_audit(
            evidence[0],
            other_path,
            attempt_id=_ATTEMPT,
            phase_name="schematic",
            server_name=_SERVER,
        )


def test_modified_server_trace_refuses_gateway_confirmation(evidence: tuple[Path, Path]) -> None:
    server, _ = evidence
    server.write_text(server.read_text().replace("kicad_get_version", "drc_rule_delete", 1))
    with pytest.raises(ReferenceOpsGatewayAuditError):
        _reconcile(evidence)


def test_gateway_witness_parser_rejects_malformed_json_directly() -> None:
    with pytest.raises(ReferenceOpsGatewayAuditError, match="invalid Gateway witness JSON"):
        reference_ops_gateway_audit._witness_rows(b"{malformed", _SERVER)


def test_gateway_match_rejects_tool_call_count_mismatch_directly() -> None:
    with pytest.raises(ReferenceOpsGatewayAuditError, match="Gateway/server call counts differ"):
        reference_ops_gateway_audit._match_gateway_server_events(
            rows=[],
            calls=[],
            results=[],
            pairs=[("kicad_get_version", "completed")],
            server_name=_SERVER,
        )


def test_rejects_gateway_success_when_server_reports_failure(
    evidence: tuple[Path, Path],
) -> None:
    """A successful Gateway transport must not mask a failed MCP tool result."""
    server, _witness = evidence
    events = [json.loads(line) for line in server.read_text(encoding="utf-8").splitlines()]
    first_result = next(event for event in events if event["event_type"] == "tool_result")
    first_result["status"] = "failed"
    server.write_text(
        "\n".join(json.dumps(event, sort_keys=True) for event in events) + "\n",
        encoding="utf-8",
    )
    # The independent gateway still reports both calls as 'ok'.
    with pytest.raises(ReferenceOpsGatewayAuditError, match="Gateway failure disagrees"):
        _reconcile(evidence)
