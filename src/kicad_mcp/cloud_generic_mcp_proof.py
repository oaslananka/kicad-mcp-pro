"""Verify an issuer-signed single-use remote MCP mutation on the owner device.

No arbitrary network token, key, tool name or local path is trusted. Signature,
current grant, signed Connector identity, owner foreground mode and replay
reservation are independent gates. An authorized local MCP tool supplies the
engineering transaction semantics.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from kicad_mcp.cloud_generic_mcp_bridge import is_generic_cloud_tool_safe
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_write_proof import _decode_bounded
from kicad_mcp.operating_modes import OperatingMode, tool_required_mode
from kicad_mcp.tools.router import tools_for_profile

_DOMAIN = b"kicad-cloud-signed-mcp-tool-v1\x00"
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_TOOL = re.compile(r"[a-z][a-z0-9_]{0,127}", re.ASCII)
_HASH = re.compile(r"[a-f0-9]{64}")
_KEYS = frozenset(
    {
        "kind",
        "version",
        "requestId",
        "deviceId",
        "projectId",
        "sessionId",
        "deadlineUnixMs",
        "toolName",
        "argumentsSha256",
    }
)
_DENIED = "signed_mcp_operation_denied"


class GenericMcpProofDeniedError(ValueError):
    """The signed proposal or the requested operation cannot be trusted."""


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len(pairs) != len(dict(pairs)):
        raise GenericMcpProofDeniedError(_DENIED)
    return dict(pairs)


def _strict_json(value: bytes) -> object:
    try:
        return json.loads(
            value.decode("utf8"),
            object_pairs_hook=_unique_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(GenericMcpProofDeniedError(_DENIED)),
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise GenericMcpProofDeniedError(_DENIED) from exc


def verify_generic_mcp_write_proof(
    proof: bytes,
    *,
    arguments_json: str,
    trusted_issuer_key: Ed25519PublicKey,
    verified: VerifiedLocalBinding,
    operator_project: OperatorProject,
    now_unix_ms: int,
    consume_once: Callable[[str, str], bool],
) -> dict[str, Any]:
    """Match signature, exact serialized args, local binding, TTL and replay."""
    if (
        not isinstance(proof, bytes)
        or not 1 <= len(proof) <= 2048
        or not isinstance(arguments_json, str)
        or not 0 < len(arguments_json.encode("utf8")) <= 32768
        or not isinstance(trusted_issuer_key, Ed25519PublicKey)
        or type(now_unix_ms) is not int
        or not callable(consume_once)
    ):
        raise GenericMcpProofDeniedError(_DENIED)
    parsed = _strict_json(proof)
    if (
        not isinstance(parsed, dict)
        or set(parsed) != {"kind", "version", "payload", "signature"}
        or parsed.get("kind") != "connector.signed_mcp_tool"
        or type(parsed.get("version")) is not int
        or parsed["version"] != 1
    ):
        raise GenericMcpProofDeniedError(_DENIED)
    try:
        payload = _decode_bounded(parsed["payload"], max_bytes=1024)
        signature = _decode_bounded(parsed["signature"], max_bytes=64)
        trusted_issuer_key.verify(signature, _DOMAIN + payload)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise GenericMcpProofDeniedError(_DENIED) from exc
    cmd = _strict_json(payload)
    if not isinstance(cmd, dict) or set(cmd) != _KEYS:
        raise GenericMcpProofDeniedError(_DENIED)
    request_id = cmd.get("requestId")
    tool = cmd.get("toolName")
    deadline = cmd.get("deadlineUnixMs")
    args_sha = cmd.get("argumentsSha256")
    if (
        cmd.get("kind") != "connector.mcp_tool_write"
        or type(cmd.get("version")) is not int
        or cmd["version"] != 1
        or any(
            not isinstance(cmd.get(k), str) or _UUID.fullmatch(cmd[k]) is None
            for k in ("requestId", "deviceId", "projectId", "sessionId")
        )
        or verified.operations != frozenset({"mcp_bridge"})
        or verified.device_id != operator_project.device_id
        or verified.project_id != operator_project.project_id
        or cmd["deviceId"] != verified.device_id
        or cmd["projectId"] != verified.project_id
        or cmd["sessionId"] != verified.session_id
        or type(deadline) is not int
        or not now_unix_ms < deadline <= now_unix_ms + 10_000
        or deadline > verified.session_expires_unix_ms
        or not isinstance(tool, str)
        or _TOOL.fullmatch(tool) is None
        or tool not in tools_for_profile("expert")
        or not is_generic_cloud_tool_safe(tool)
        or tool_required_mode(tool) != OperatingMode.WRITE
        or not isinstance(args_sha, str)
        or _HASH.fullmatch(args_sha) is None
        or hashlib.sha256(arguments_json.encode("utf8")).hexdigest() != args_sha
    ):
        raise GenericMcpProofDeniedError(_DENIED)
    args = _strict_json(arguments_json.encode("utf8"))
    if not isinstance(args, dict):
        raise GenericMcpProofDeniedError(_DENIED)
    try:
        once = consume_once(str(verified.session_id), str(request_id))
    except Exception as exc:
        raise GenericMcpProofDeniedError(_DENIED) from exc
    if once is not True:
        raise GenericMcpProofDeniedError(_DENIED)
    return {
        "toolName": tool,
        "arguments": args,
        "requestId": request_id,
        "projectId": cmd["projectId"],
        "deadlineUnixMs": deadline,
    }
