"""General MCP calls must be signed without turning Cloud into a code executor."""

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_generic_mcp_proof import (
    GenericMcpProofDeniedError,
    verify_generic_mcp_write_proof,
)
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
NOW = 3000000000000


def frame(
    key, *, name="sch_add_symbol", args='{"reference":"R1"}', session=SESSION, deadline=NOW + 5000
) -> tuple[bytes, str]:
    payload = json.dumps(
        {
            "kind": "connector.mcp_tool_write",
            "version": 1,
            "requestId": REQUEST,
            "deviceId": DEVICE,
            "projectId": PROJECT,
            "sessionId": session,
            "deadlineUnixMs": deadline,
            "toolName": name,
            "argumentsSha256": hashlib.sha256(args.encode()).hexdigest(),
        },
        separators=(",", ":"),
    ).encode()
    prefix = b"kicad-cloud-signed-mcp-tool-v1\x00".replace(b"\x00", b"\x00")
    signature = key.sign(prefix + payload)
    proof = json.dumps(
        {
            "kind": "connector.signed_mcp_tool",
            "version": 1,
            "payload": base64.urlsafe_b64encode(payload).decode().rstrip("="),
            "signature": base64.urlsafe_b64encode(signature).decode().rstrip("="),
        },
        separators=(",", ":"),
    ).encode()
    return proof, args


def test_valid_exact_signed_write_and_crash_durable_replay(tmp_path) -> None:
    k = Ed25519PrivateKey.generate()
    proof, args = frame(k)
    verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"mcp_bridge"}),
        session_expires_unix_ms=NOW + 20000,
    )
    op = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="test"
    )
    seen = set()

    def consume(session, request):
        value = (session, request)
        if value in seen:
            return False
        seen.add(value)
        return True

    kw = dict(
        trusted_issuer_key=k.public_key(),
        verified=verified,
        operator_project=op,
        now_unix_ms=NOW,
        consume_once=consume,
    )
    cmd = verify_generic_mcp_write_proof(proof, arguments_json=args, **kw)
    assert cmd["toolName"] == "sch_add_symbol"
    assert cmd["arguments"] == {"reference": "R1"}
    with pytest.raises(GenericMcpProofDeniedError):
        verify_generic_mcp_write_proof(proof, arguments_json=args, **kw)


@pytest.mark.parametrize("change", ["args", "session", "deadline", "name", "signature"])
def test_forgery_rejected(tmp_path, change) -> None:
    k = Ed25519PrivateKey.generate()
    proof, args = frame(
        k,
        session=("55555555-5555-4555-8555-555555555555" if change == "session" else SESSION),
        deadline=(NOW + 11000 if change == "deadline" else NOW + 5000),
        name=("export_manufacturing_package" if change == "name" else "sch_add_symbol"),
    )
    if change == "args":
        args = '{"reference":"R2"}'
    if change == "signature":
        data = json.loads(proof)
        data["signature"] = "a" + data["signature"][1:]
        proof = json.dumps(data).encode()
    verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"mcp_bridge"}),
        session_expires_unix_ms=NOW + 20000,
    )
    op = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="test"
    )
    _prevalidated_115_trusted_issuer_key = k.public_key()
    with pytest.raises(GenericMcpProofDeniedError):
        verify_generic_mcp_write_proof(
            proof,
            arguments_json=args,
            trusted_issuer_key=_prevalidated_115_trusted_issuer_key,
            verified=verified,
            operator_project=op,
            now_unix_ms=NOW,
            consume_once=lambda a, b: True,
        )
