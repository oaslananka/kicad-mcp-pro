"""Bounded, generic MCP execution on the owner's existing signed Connector.

No Cloud caller can pick filesystem paths, operating profiles, arbitrary
subprocess commands, or bypass native owner write consent. The current local
MCP server remains the single source of real tool behavior.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from mcp.client.session import ClientSession

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
_MCP_RESULT_KIND = "connector.mcp_result"
# The Cloud overall request deadline is 75s. Leave room for worker shutdown,
# signed WebSocket delivery and ACK even when a cold local read stalls.
_READ_ONLY_MCP_CALL_BUDGET_SECONDS = 65.0
# PCB Editor diagnostics must remain usable while GUI IPC is starting or stalled.
# Keep this separate from the longer, full-fidelity DRC/ERC read budget.
_IPC_READINESS_BUDGET_SECONDS = 20.0
_BUDGETED_READ_TOOLS = frozenset({"run_drc", "run_erc", "kicad_get_server_info"})


class GenericMcpTransportError(ValueError):
    """Invalid, unauthenticated, stale or unauthorized generic Cloud MCP."""


def _response_size(response: dict[str, object]) -> int:
    return len(json.dumps(response, ensure_ascii=False).encode("utf8"))


def _matching_structured_reply(result: dict[str, object]) -> dict[str, object] | None:
    """Return verified duplicate structured data, never guess at text contents."""
    structured = result.get("structuredContent")
    contents = result.get("content")
    if not isinstance(structured, dict) or not isinstance(contents, list) or len(contents) != 1:
        return None
    text_item = contents[0]
    if (
        not isinstance(text_item, dict)
        or set(text_item) != {"type", "text"}
        or text_item.get("type") != "text"
        or not isinstance(text_item.get("text"), str)
    ):
        return None
    try:
        return structured if json.loads(text_item["text"]) == structured else None
    except (TypeError, ValueError):
        return None


def _deduplicate_mcp_text(
    response: dict[str, object], result: dict[str, object]
) -> dict[str, object] | None:
    """Replace only redundant JSON text; keep the original structured result intact."""
    structured = _matching_structured_reply(result)
    if structured is None:
        return None
    summary = structured.get("summary")
    fallback = (
        summary
        if isinstance(summary, str) and 0 < len(summary) <= 2048
        else "Full findings are available in structuredContent."
    )
    readable = structured.get("text")
    displays = (readable, fallback) if isinstance(readable, str) and readable else (fallback,)
    for display in displays:
        candidate = {
            **response,
            "result": {**result, "content": [{"type": "text", "text": display}]},
        }
        if _response_size(candidate) <= _MAX_RESULT_BYTES:
            return candidate
    return None


def _fit_cloud_mcp_response(
    response: dict[str, object], *, write_approved: bool = False
) -> dict[str, object]:
    """Fit duplicate MCP text/structured renders inside the existing signed frame cap.

    The local MCP response can contain the same full DRC findings twice, as
    JSON text and structured data. Only a proven duplicate may be shortened.
    """
    if _response_size(response) <= _MAX_RESULT_BYTES:
        return response
    result = response.get("result")
    if response.get("method") != "call" or not isinstance(result, dict):
        raise GenericMcpTransportError("mcp_bridge_result_too_large")
    reduced = _deduplicate_mcp_text(response, result)
    if reduced is not None:
        return reduced
    # A mutating tool might have successfully changed the board even if its
    # response is oversized: preserve the unknown-outcome error, never imply
    # that retrying is safe.
    if write_approved:
        raise GenericMcpTransportError("mcp_bridge_result_too_large")
    # A read-only tool can return an explicit, bounded failure while retaining
    # its signed request/ack session and without exposing unique private data.
    return {
        **response,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": (
                        "mcp_bridge_result_too_large: The local tool produced more data "
                        "than this bounded Cloud connection can return. "
                        "Use a narrower read-only report or inspect the local result."
                    ),
                }
            ],
            "isError": True,
            "resultType": "complete",
        },
    }


def _read_timeout_reply(frame: dict[str, Any], project: OperatorProject) -> dict[str, object]:
    """A signed, bounded tool failure: a slow read is not a lost device pairing."""
    return {
        "kind": _MCP_RESULT_KIND,
        "version": 1,
        "requestId": frame["requestId"],
        "projectId": project.project_id,
        "method": "call",
        "ok": True,
        "result": {
            "isError": True,
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Local KiCad diagnostic timed out before its full result was available. "
                        "This does not establish that the device needs to re-pair. "
                        "Check that the selected project and local KiCad CLI are responsive, "
                        "then retry this read-only check."
                    ),
                }
            ],
            "structuredContent": {
                "success": False,
                "reason": "local_mcp_read_timeout",
            },
        },
    }


def _validated_owner_stem(value: object) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 180
        or value in {".", ".."}
        or value.endswith(".")
        or any(char in value for char in ("/", "\\", ":", "\x00"))
    ):
        raise GenericMcpTransportError(_DENIED)
    return value


def _unique_owner_file(root: Path, stem: str, suffix: str, resolved: Path) -> Path | None:
    files = list(root.glob("*" + suffix))
    if not files:
        return None
    selected = root / (stem + suffix)
    if len(files) != 1 or files[0] != selected or selected.is_symlink():
        raise GenericMcpTransportError(_DENIED)
    if selected.resolve(strict=True).parent != resolved:
        raise GenericMcpTransportError(_DENIED)
    return selected


def _owner_project_files(project: OperatorProject) -> dict[str, str]:
    """Pin the exactly selected local KiCad project, never Cloud-provided paths."""
    if not isinstance(project, OperatorProject):
        raise GenericMcpTransportError(_DENIED)
    root = project.directory
    stem = _validated_owner_stem(project.filename_stem)
    if not isinstance(root, Path) or not root.is_absolute():
        raise GenericMcpTransportError(_DENIED)
    try:
        resolved = root.resolve(strict=True)
        if not root.is_dir() or root.is_symlink():
            raise GenericMcpTransportError(_DENIED)
        if _unique_owner_file(root, stem, ".kicad_pro", resolved) is None:
            raise GenericMcpTransportError(_DENIED)
        selected = {"project_dir": str(resolved)}
        for suffix, field in ((".kicad_pcb", "pcb_file"), (".kicad_sch", "sch_file")):
            chosen = _unique_owner_file(root, stem, suffix, resolved)
            if chosen is not None:
                selected[field] = chosen.name
        if len(selected) == 1:
            raise GenericMcpTransportError(_DENIED)
        return selected
    except (OSError, TypeError, ValueError) as exc:
        raise GenericMcpTransportError(_DENIED) from exc


def _require_owner_live_pcb(project: OperatorProject) -> None:
    """Re-use the canonical native KiCad GUI-to-owner-project identity guard.

    A locally activated project directory does not imply that the separately
    running PCB Editor is displaying that same board. For mutating pcb_* tools,
    refuse if native IPC is unavailable or is bound to another board.
    """
    try:
        from kicad_mcp.cloud_write_native_ipc import _require_approved_live_board
        from kicad_mcp.connection import get_board

        _require_approved_live_board(get_board(), project)
    except Exception as exc:
        raise GenericMcpTransportError(_DENIED) from exc


_BASE_FIELDS = frozenset({"kind", "version", "requestId", "projectId", "method"})
_CATALOG_FIELDS = _BASE_FIELDS | {"offset"}
_CALL_FIELDS = _BASE_FIELDS | {"toolName", "argumentsJson"}


def _validate_mcp_frame(frame: dict[str, Any]) -> None:
    if (
        not isinstance(frame, dict)
        or frame.get("kind") != "connector.mcp_request"
        or type(frame.get("version")) is not int
        or frame.get("version") != 1
        or not isinstance(frame.get("requestId"), str)
        or _UUID.fullmatch(frame["requestId"]) is None
        or not isinstance(frame.get("projectId"), str)
        or _UUID.fullmatch(frame["projectId"]) is None
    ):
        raise GenericMcpTransportError(_DENIED)
    if frame.get("method") == "catalog":
        _validate_catalog_frame(frame)
    elif frame.get("method") == "call":
        _validate_call_frame(frame)
    else:
        raise GenericMcpTransportError(_DENIED)


def _validate_catalog_frame(frame: dict[str, Any]) -> None:
    tool = frame.get("toolName")
    if (
        set(frame) not in (_CATALOG_FIELDS, _CATALOG_FIELDS | {"toolName"})
        or type(frame.get("offset")) is not int
        or not 0 <= frame["offset"] <= 512
        or ("toolName" in frame and (not isinstance(tool, str) or _NAME.fullmatch(tool) is None))
    ):
        raise GenericMcpTransportError(_DENIED)


def _validate_call_frame(frame: dict[str, Any]) -> None:
    tool = frame.get("toolName")
    args = frame.get("argumentsJson")
    if (
        set(frame) not in (_CALL_FIELDS, _CALL_FIELDS | {"proof"})
        or not isinstance(tool, str)
        or _NAME.fullmatch(tool) is None
        or not isinstance(args, str)
        or len(args.encode("utf8")) > 32_768
    ):
        raise GenericMcpTransportError(_DENIED)


@dataclass(frozen=True, slots=True)
class _ApprovedCall:
    name: str
    arguments: Any
    write_approved: bool
    deadline: int | None


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

    def _current_project(self, project_id: str) -> OperatorProject:
        if self.authorized() is not True:
            raise GenericMcpTransportError(_DENIED)
        project = self.local_project(project_id)
        if not isinstance(project, OperatorProject) or project.device_id != self.receipt.device_id:
            raise GenericMcpTransportError(_DENIED)
        return project

    def _verify_write(
        self, frame: dict[str, Any], project: OperatorProject, binding: VerifiedLocalBinding
    ) -> int:
        proof = frame.get("proof")
        if not isinstance(proof, dict) or not isinstance(self.issuer, Ed25519PublicKey):
            raise GenericMcpTransportError(_DENIED)
        consumer = self.consume_once
        if consumer is None:
            raise GenericMcpTransportError(_DENIED)
        proof_bytes = json.dumps(proof, separators=(",", ":"), ensure_ascii=False).encode("utf8")
        details = verify_generic_mcp_write_proof(
            proof_bytes,
            arguments_json=frame["argumentsJson"],
            trusted_issuer_key=self.issuer,
            verified=binding,
            operator_project=project,
            now_unix_ms=time.time_ns() // 1_000_000,
            consume_once=consumer,
        )
        if details["requestId"] != frame["requestId"] or details["toolName"] != frame["toolName"]:
            raise GenericMcpTransportError(_DENIED)
        if frame["toolName"].startswith("pcb_"):
            _require_owner_live_pcb(project)
        deadline = details["deadlineUnixMs"]
        if type(deadline) is not int:
            raise GenericMcpTransportError(_DENIED)
        return deadline

    def _prepare_call(
        self, frame: dict[str, Any], project: OperatorProject, binding: VerifiedLocalBinding
    ) -> _ApprovedCall:
        name = frame["toolName"]
        required = tool_required_mode(name)
        if required not in (OperatingMode.READONLY, OperatingMode.WRITE):
            raise GenericMcpTransportError(_DENIED)
        if required == OperatingMode.WRITE and not self.allow_write:
            raise GenericMcpTransportError(_DENIED)
        deadline = None
        if required == OperatingMode.WRITE:
            deadline = self._verify_write(frame, project, binding)
        elif "proof" in frame:
            raise GenericMcpTransportError(_DENIED)
        try:
            arguments = json.loads(frame["argumentsJson"])
        except (ValueError, TypeError) as exc:
            raise GenericMcpTransportError(_DENIED) from exc
        return _ApprovedCall(
            name=name,
            arguments=arguments,
            write_approved=required == OperatingMode.WRITE,
            deadline=deadline,
        )

    @staticmethod
    async def _activate_owner_worker(worker: ClientSession, selection: dict[str, str]) -> None:
        activated = await worker.call_tool("kicad_set_project", arguments=selection)
        if getattr(activated, "isError", False) is True:
            raise GenericMcpTransportError("mcp_owner_project_activation_failed")
        if any(
            getattr(item, "type", None) == "text"
            and str(getattr(item, "text", "")).startswith(
                ("E_PROJECT_", "Project directory does not exist")
            )
            for item in getattr(activated, "content", [])
        ):
            raise GenericMcpTransportError("mcp_owner_project_activation_failed")

    async def _worker_result(
        self,
        frame: dict[str, Any],
        project: OperatorProject,
        bridge: GenericProjectMcpBridge,
        call: _ApprovedCall | None,
    ) -> dict[str, object]:
        selection = _owner_project_files(project)
        mode = "write" if self.allow_write else "readonly"
        async with project_stdio_worker(
            project.directory, profile="expert", operating_mode=mode
        ) as worker:
            if self.authorized() is not True:
                raise GenericMcpTransportError(_DENIED)
            await self._activate_owner_worker(worker, selection)
            if self.authorized() is not True:
                raise GenericMcpTransportError(_DENIED)
            if frame["method"] == "catalog":
                catalog = await bridge.list_tools(
                    worker, project_id=project.project_id, session_id=self.receipt.session_id
                )
                lookup = frame.get("toolName")
                if isinstance(lookup, str):
                    catalog = [item for item in catalog if item["name"] == lookup]
                offset = frame["offset"]
                tools = catalog[offset : offset + _PAGE_SIZE]
                next_offset = offset + len(tools)
                return {
                    "kind": _MCP_RESULT_KIND,
                    "version": 1,
                    "requestId": frame["requestId"],
                    "projectId": project.project_id,
                    "method": "catalog",
                    "ok": True,
                    "tools": tools,
                    "nextOffset": next_offset if next_offset < len(catalog) else None,
                }
            if call is None:
                raise GenericMcpTransportError(_DENIED)
            result = await bridge.call_tool(
                worker,
                project_id=project.project_id,
                session_id=self.receipt.session_id,
                name=call.name,
                arguments=call.arguments,
                write_approved=call.write_approved,
                not_after_unix_ms=call.deadline,
            )
            return {
                "kind": _MCP_RESULT_KIND,
                "version": 1,
                "requestId": frame["requestId"],
                "projectId": project.project_id,
                "method": "call",
                "ok": True,
                "result": result,
            }

    async def _bounded_worker_result(
        self,
        frame: dict[str, Any],
        project: OperatorProject,
        bridge: GenericProjectMcpBridge,
        call: _ApprovedCall | None,
    ) -> dict[str, object]:
        if call is None or call.write_approved or call.name not in _BUDGETED_READ_TOOLS:
            return await self._worker_result(frame, project, bridge, call)
        budget = (
            _IPC_READINESS_BUDGET_SECONDS
            if call.name == "kicad_get_server_info"
            else _READ_ONLY_MCP_CALL_BUDGET_SECONDS
        )
        try:
            async with asyncio.timeout(budget):
                return await self._worker_result(frame, project, bridge, call)
        except TimeoutError:
            return _read_timeout_reply(frame, project)

    async def dispatch(self, frame: dict[str, Any]) -> dict[str, object]:
        _validate_mcp_frame(frame)
        try:
            project = self._current_project(frame["projectId"])
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
            call = (
                self._prepare_call(frame, project, binding) if frame["method"] == "call" else None
            )
            response = await self._bounded_worker_result(frame, project, bridge, call)
            if self.authorized() is not True:
                raise GenericMcpTransportError(_DENIED)
            response = _fit_cloud_mcp_response(
                response, write_approved=bool(call and call.write_approved)
            )
            if _response_size(response) > _MAX_RESULT_BYTES:
                raise GenericMcpTransportError("mcp_bridge_result_too_large")
            return response
        except GenericMcpTransportError:
            raise
        except Exception as exc:
            raise GenericMcpTransportError(_DENIED) from exc
