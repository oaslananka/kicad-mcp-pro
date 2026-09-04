"""Protocol compatibility helpers for opt-in MCP release-candidate lanes.

The production server remains on the stable MCP Python SDK. This module owns
only pure request/response envelope validation and adaptation so candidate
contracts can be exercised without leaking prerelease SDK behavior into the
stable runtime.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

CANDIDATE_PROTOCOL_LANE = "2026-07-28-rc"
CANDIDATE_PROTOCOL_VERSION = "2026-07-28"
SERVER_NAME = "kicad-mcp-pro"
JSONRPCID = str | int | None
SERVER_INSTRUCTIONS = (
    "KiCad MCP Pro provides bounded tools, prompts, and resources for inspecting, "
    "authoring, validating, and releasing KiCad projects. Tool visibility remains "
    "subject to authentication, profile, operating mode, and live KiCad capabilities."
)

_NAMED_METHOD_FIELDS = {
    "tools/call": "name",
    "prompts/get": "name",
    "resources/read": "uri",
}
_LEGACY_LIFECYCLE_METHODS = {"initialize", "notifications/initialized"}
_CACHE_POLICY = {
    "tools/list": (300_000, "private"),
    "prompts/list": (300_000, "private"),
    "resources/list": (300_000, "private"),
    "resources/templates/list": (300_000, "private"),
    "resources/read": (60_000, "private"),
}


class ProtocolValidationError(ValueError):
    """A JSON-RPC error raised while validating a candidate protocol request."""

    def __init__(
        self,
        code: int,
        message: str,
        *,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data) if data is not None else None


@dataclass(frozen=True, slots=True)
class CandidateRequest:
    """Validated routing metadata extracted from a candidate request."""

    method: str
    name: str | None
    request_id: JSONRPCID


def _normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {str(key).casefold(): str(value) for key, value in headers.items()}


def _decode_header_value(value: str, *, header: str) -> str:
    prefix = "=?base64?"
    suffix = "?="
    if not value.startswith(prefix):
        return value
    if not value.endswith(suffix):
        raise ProtocolValidationError(
            -32020,
            f"Invalid Base64 sentinel encoding for {header}",
            data={"header": header},
        )
    encoded = value[len(prefix) : -len(suffix)]
    try:
        raw = base64.b64decode(encoded, validate=True)
        return raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ProtocolValidationError(
            -32020,
            f"Invalid Base64 sentinel encoding for {header}",
            data={"header": header},
        ) from exc


def validate_candidate_request(
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> CandidateRequest:
    """Validate candidate transport headers and required per-request metadata."""

    normalized = _normalized_headers(headers)

    if payload.get("jsonrpc") != "2.0":
        raise ProtocolValidationError(-32600, "JSON-RPC request jsonrpc must be '2.0'")

    raw_request_id = payload.get("id")
    if not isinstance(raw_request_id, (str, int)) or isinstance(raw_request_id, bool):
        raise ProtocolValidationError(
            -32600,
            "JSON-RPC request id must be a string or integer",
        )
    request_id: JSONRPCID = raw_request_id

    if "mcp-session-id" in normalized:
        raise ProtocolValidationError(
            -32020,
            "Mcp-Session-Id is not permitted by the stateless 2026-07-28 contract",
            data={"header": "Mcp-Session-Id"},
        )

    header_version = normalized.get("mcp-protocol-version")
    if header_version != CANDIDATE_PROTOCOL_VERSION:
        raise ProtocolValidationError(
            -32022,
            f"Unsupported protocol version: {header_version or '<missing>'}",
            data={
                "supportedVersions": [CANDIDATE_PROTOCOL_VERSION],
                "receivedVersion": header_version,
            },
        )

    method = payload.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolValidationError(-32600, "JSON-RPC request method must be a non-empty string")

    method_header = normalized.get("mcp-method")
    if method_header != method:
        raise ProtocolValidationError(
            -32020,
            (
                f"Header mismatch: Mcp-Method value {method_header!r} "
                f"does not match body method {method!r}"
            ),
            data={"header": "Mcp-Method", "expected": method, "received": method_header},
        )

    if method in _LEGACY_LIFECYCLE_METHODS:
        raise ProtocolValidationError(
            -32601,
            f"Method {method!r} is not available in MCP 2026-07-28",
            data={"method": method},
        )

    params_raw = payload.get("params")
    if not isinstance(params_raw, Mapping):
        raise ProtocolValidationError(-32602, "Request params must be an object")
    params = cast(Mapping[str, Any], params_raw)
    meta_raw = params.get("_meta")
    if not isinstance(meta_raw, Mapping):
        raise ProtocolValidationError(-32602, "Request params._meta must be an object")
    meta = cast(Mapping[str, Any], meta_raw)

    body_version = meta.get("io.modelcontextprotocol/protocolVersion")
    if body_version != header_version:
        raise ProtocolValidationError(
            -32020,
            "Header/body protocol version mismatch",
            data={"headerVersion": header_version, "bodyVersion": body_version},
        )

    if "io.modelcontextprotocol/clientCapabilities" not in meta:
        raise ProtocolValidationError(
            -32021,
            (
                "Missing required client capability metadata: "
                "io.modelcontextprotocol/clientCapabilities"
            ),
            data={"capability": "io.modelcontextprotocol/clientCapabilities"},
        )
    capabilities = meta["io.modelcontextprotocol/clientCapabilities"]
    if not isinstance(capabilities, Mapping):
        raise ProtocolValidationError(
            -32021,
            "Client capability metadata must be an object",
            data={"capability": "io.modelcontextprotocol/clientCapabilities"},
        )

    name: str | None = None
    source_field = _NAMED_METHOD_FIELDS.get(method)
    if source_field is not None:
        source_value = params.get(source_field)
        if not isinstance(source_value, str) or not source_value:
            raise ProtocolValidationError(
                -32602,
                f"{method} requires params.{source_field}",
                data={"field": f"params.{source_field}"},
            )
        encoded_name = normalized.get("mcp-name")
        decoded_name = (
            _decode_header_value(encoded_name, header="Mcp-Name")
            if encoded_name is not None
            else None
        )
        if decoded_name != source_value:
            raise ProtocolValidationError(
                -32020,
                (
                    f"Header mismatch: Mcp-Name value {decoded_name!r} "
                    f"does not match body value {source_value!r}"
                ),
                data={
                    "header": "Mcp-Name",
                    "expected": source_value,
                    "received": decoded_name,
                },
            )
        name = source_value

    return CandidateRequest(method=method, name=name, request_id=request_id)


def candidate_discover_result(*, server_version: str) -> dict[str, Any]:
    """Build the mandatory candidate `server/discover` result."""

    return {
        "resultType": "complete",
        "supportedVersions": [CANDIDATE_PROTOCOL_VERSION],
        "capabilities": {
            "tools": {},
            "prompts": {},
            "resources": {},
            "extensions": {},
        },
        "_meta": {
            "io.modelcontextprotocol/serverInfo": {
                "name": SERVER_NAME,
                "version": server_version,
            }
        },
        "instructions": SERVER_INSTRUCTIONS,
        "ttlMs": 3_600_000,
        "cacheScope": "private",
    }


_CANDIDATE_REQUEST_META_KEYS = (
    "io.modelcontextprotocol/protocolVersion",
    "io.modelcontextprotocol/clientCapabilities",
    "io.modelcontextprotocol/clientInfo",
)


def _strip_candidate_request_metadata(params_raw: object) -> None:
    if not isinstance(params_raw, dict):
        return
    params = cast(dict[str, Any], params_raw)
    meta_raw = params.get("_meta")
    if not isinstance(meta_raw, dict):
        return
    meta = cast(dict[str, Any], meta_raw)
    for key in _CANDIDATE_REQUEST_META_KEYS:
        meta.pop(key, None)
    if not meta:
        params.pop("_meta", None)


def stable_sdk_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove candidate-only request metadata before invoking the stable SDK."""

    translated: dict[str, Any] = deepcopy(dict(payload))
    _strip_candidate_request_metadata(translated.get("params"))
    return translated


def _candidate_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    result_raw = payload.get("result")
    if not isinstance(result_raw, dict):
        return None
    return cast(dict[str, Any], result_raw)


def _decorate_server_info(result: dict[str, Any], server_version: str) -> None:
    meta_raw = result.setdefault("_meta", {})
    if isinstance(meta_raw, dict):
        meta = cast(dict[str, Any], meta_raw)
    else:
        meta = {}
        result["_meta"] = meta
    meta["io.modelcontextprotocol/serverInfo"] = {
        "name": SERVER_NAME,
        "version": server_version,
    }


def _decorate_cache_policy(method: str, result: dict[str, Any]) -> None:
    cache_policy = _CACHE_POLICY.get(method)
    if cache_policy is None:
        return
    ttl_ms, scope = cache_policy
    result.setdefault("ttlMs", ttl_ms)
    result.setdefault("cacheScope", scope)


def _sorted_tool_list(tools_raw: object) -> list[dict[str, Any]] | None:
    if not isinstance(tools_raw, list):
        return None
    tools: list[dict[str, Any]] = []
    for item in tools_raw:
        if not isinstance(item, dict):
            return None
        tools.append(cast(dict[str, Any], item))
    tools.sort(key=lambda tool: str(tool.get("name", "")))
    return tools


def _decorate_tool_list(method: str, result: dict[str, Any]) -> None:
    if method != "tools/list":
        return
    tools = _sorted_tool_list(result.get("tools"))
    if tools is not None:
        result["tools"] = tools


def decorate_candidate_response(
    method: str,
    payload: Mapping[str, Any],
    *,
    server_version: str,
) -> dict[str, Any]:
    """Decorate a stable SDK JSON-RPC response for the candidate contract."""

    decorated: dict[str, Any] = deepcopy(dict(payload))
    result = _candidate_result(decorated)
    if result is not None:
        result.setdefault("resultType", "complete")
        _decorate_server_info(result, server_version)
        _decorate_cache_policy(method, result)
        _decorate_tool_list(method, result)
    return decorated


def jsonrpc_error_response(
    error: ProtocolValidationError,
    *,
    request_id: JSONRPCID = None,
) -> dict[str, Any]:
    """Render a candidate protocol validation error as JSON-RPC."""

    error_payload: dict[str, Any] = {"code": error.code, "message": error.message}
    if error.data is not None:
        error_payload["data"] = deepcopy(error.data)
    return {"jsonrpc": "2.0", "id": request_id, "error": error_payload}
