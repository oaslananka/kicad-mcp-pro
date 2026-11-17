"""Bounded, generic MCP execution on the owner's existing signed Connector.

No Cloud caller can pick filesystem paths, operating profiles, arbitrary
subprocess commands, or bypass native owner write consent. The current local
MCP server remains the single source of real tool behavior.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from kicad_mcp.cloud_generic_mcp_bridge import GenericProjectMcpBridge
from kicad_mcp.cloud_generic_mcp_proof import verify_generic_mcp_write_proof
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.operating_modes import OperatingMode, tool_required_mode
from kicad_mcp.project.stdio_worker import project_stdio_worker

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.I)
_NAME = re.compile(r"[a-z][a-z0-9_]{0,127}", re.ASCII)
_DENIED = "mcp_bridge_request_denied"
_PAGE_SIZE = 8
_MAX_RESULT_BYTES = 60_000


class GenericMcpTransportError(ValueError):
    """Invalid, unauthenticated, stale or unauthorized generic Cloud MCP."""


class GenericProjectMcpService:
    def __init__(
        self,
        *,
        receipt: HandshakeReceipt,
        local_project: Callable[[str], OperatorProject | None],
        current_authorization: Callable[[], bool],
        allow_native_write: bool = False,
        trusted_issuer_key: Ed25519PublicKey | None = None,
        consume_once: Callable[[str, str], bool] | None = None,
    ) -> None:
        if (
            not isinstance(receipt, HandshakeReceipt)
            or not callable(local_project)
            or not callable(current_authorization)
            or type(allow_native_write) is not bool
            or (
                allow_native_write
                and (
                    not isinstance(trusted_issuer_key, Ed25519PublicKey)
                    or not callable(consume_once)
                )
            )
        ):
            raise GenericMcpTransportError(_DENIED)
        self.receipt = receipt
        self.local_project = local_project
        self.authorized = current_authorization
        self.allow_write = allow_native_write
        self.issuer = trusted_issuer_key
        self.consume_once = consume_once

    async def dispatch(self, frame: dict[str, Any]) -> dict[str, object]:
        if (
            not isinstance(frame, dict)
            or frame.get("kind") != "connector.mcp_request"
            or type(frame.get("version")) is not int
            or frame["version"] != 1
            or not isinstance(frame.get("requestId"), str)
            or _UUID.fullmatch(frame["requestId"]) is None
            or not isinstance(frame.get("projectId"), str)
            or _UUID.fullmatch(frame["projectId"]) is None
            or frame.get("method") not in ("catalog", "call")
            or (
                frame["method"] == "catalog"
                and (
                    set(frame)
                    not in (
                        {"kind", "version", "requestId", "projectId", "method", "offset"},
                        {
                            "kind",
                            "version",
                            "requestId",
                            "projectId",
                            "method",
                            "offset",
                            "toolName",
                        },
                    )
                    or type(frame.get("offset")) is not int
                    or not 0 <= frame["offset"] <= 512
                    or (
                        "toolName" in frame
                        and (
                            not isinstance(frame["toolName"], str)
                            or _NAME.fullmatch(frame["toolName"]) is None
                        )
                    )
                )
            )
            or (
                frame["method"] == "call"
                and (
                    set(frame)
                    not in (
                        {
                            "kind",
                            "version",
                            "requestId",
                            "projectId",
                            "method",
                            "toolName",
                            "argumentsJson",
                        },
                        {
                            "kind",
                            "version",
                            "requestId",
                            "projectId",
                            "method",
                            "toolName",
                            "argumentsJson",
                            "proof",
                        },
                    )
                    or not isinstance(frame.get("toolName"), str)
                    or _NAME.fullmatch(frame["toolName"]) is None
                    or not isinstance(frame.get("argumentsJson"), str)
                    or len(frame["argumentsJson"].encode("utf8")) > 32768
                )
            )
        ):
            raise GenericMcpTransportError(_DENIED)
        try:
            if self.authorized() is not True:
                raise GenericMcpTransportError(_DENIED)
            project = self.local_project(frame["projectId"])
            if (
                not isinstance(project, OperatorProject)
                or project.device_id != self.receipt.device_id
            ):
                raise GenericMcpTransportError(_DENIED)
            now = time.time_ns() // 1_000_000
            binding = VerifiedLocalBinding(
                device_id=self.receipt.device_id,
                project_id=project.project_id,
                session_id=self.receipt.session_id,
                operations=frozenset({"mcp_bridge"}),
                session_expires_unix_ms=now + 300_000,
            )
            bridge = GenericProjectMcpBridge(
                verified=binding,
                operator_project=project,
                current_authorization=self.authorized,
                allow_native_write=self.allow_write,
                profile="expert",
            )
            if frame["method"] == "call":
                name = frame["toolName"]
                required = tool_required_mode(name)
                # Fail before process startup, even if the remote caller
                # supplies an extra token or a stale signed proof.
                if required not in (OperatingMode.READONLY, OperatingMode.WRITE):
                    raise GenericMcpTransportError(_DENIED)
                if required == OperatingMode.WRITE and not self.allow_write:
                    raise GenericMcpTransportError(_DENIED)
                write_ok = False
                write_deadline: int | None = None
                if required == OperatingMode.WRITE:
                    proof = frame.get("proof")
                    if not isinstance(proof, dict) or not isinstance(self.issuer, Ed25519PublicKey):
                        raise GenericMcpTransportError(_DENIED)
                    proof_bytes = json.dumps(
                        proof, separators=(",", ":"), ensure_ascii=False
                    ).encode("utf8")
                    details = verify_generic_mcp_write_proof(
                        proof_bytes,
                        arguments_json=frame["argumentsJson"],
                        trusted_issuer_key=self.issuer,
                        verified=binding,
                        operator_project=project,
                        now_unix_ms=now,
                        consume_once=self.consume_once,
                    )
                    if details["requestId"] != frame["requestId"] or details["toolName"] != name:
                        raise GenericMcpTransportError(_DENIED)
                    write_deadline = details["deadlineUnixMs"]
                    write_ok = True
                else:
                    if "proof" in frame:
                        raise GenericMcpTransportError(_DENIED)
                try:
                    args = json.loads(frame["argumentsJson"])
                except (ValueError, TypeError) as exc:
                    raise GenericMcpTransportError(_DENIED) from exc
            mode = "write" if self.allow_write else "readonly"
            async with project_stdio_worker(
                project.directory, profile="expert", operating_mode=mode
            ) as worker:
                if frame["method"] == "catalog":
                    catalog = await bridge.list_tools(
                        worker, project_id=project.project_id, session_id=self.receipt.session_id
                    )
                    offset = frame["offset"]
                    lookup = frame.get("toolName")
                    if isinstance(lookup, str):
                        catalog = [item for item in catalog if item["name"] == lookup]
                    items = catalog[offset : offset + _PAGE_SIZE]
                    response: dict[str, object] = {
                        "kind": "connector.mcp_result",
                        "version": 1,
                        "requestId": frame["requestId"],
                        "projectId": project.project_id,
                        "method": "catalog",
                        "ok": True,
                        "tools": items,
                        "nextOffset": offset + len(items)
                        if offset + len(items) < len(catalog)
                        else None,
                    }
                else:
                    result = await bridge.call_tool(
                        worker,
                        project_id=project.project_id,
                        session_id=self.receipt.session_id,
                        name=name,
                        arguments=args,
                        write_approved=write_ok,
                        not_after_unix_ms=write_deadline,
                    )
                    response = {
                        "kind": "connector.mcp_result",
                        "version": 1,
                        "requestId": frame["requestId"],
                        "projectId": project.project_id,
                        "method": "call",
                        "ok": True,
                        "result": result,
                    }
            if self.authorized() is not True:
                raise GenericMcpTransportError(_DENIED)
            if len(json.dumps(response, ensure_ascii=False).encode("utf8")) > _MAX_RESULT_BYTES:
                raise GenericMcpTransportError("mcp_bridge_result_too_large")
            return response
        except GenericMcpTransportError:
            raise
        except Exception as exc:
            raise GenericMcpTransportError(_DENIED) from exc
