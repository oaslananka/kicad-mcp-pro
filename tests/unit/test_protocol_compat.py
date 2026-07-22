from __future__ import annotations

from copy import deepcopy

import pytest

from kicad_mcp.protocol_compat import (
    CANDIDATE_PROTOCOL_VERSION,
    ProtocolValidationError,
    candidate_discover_result,
    decorate_candidate_response,
    jsonrpc_error_response,
    stable_sdk_request,
    validate_candidate_request,
)


def candidate_request(
    method: str = "tools/list",
    *,
    params: dict[str, object] | None = None,
    request_id: object = 1,
) -> dict[str, object]:
    request_params = dict(params or {})
    request_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": CANDIDATE_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientInfo": {"name": "test-client", "version": "1.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": request_params,
    }


def candidate_headers(method: str = "tools/list", *, name: str | None = None) -> dict[str, str]:
    headers = {
        "MCP-Protocol-Version": CANDIDATE_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return headers


def assert_protocol_error(
    error: ProtocolValidationError,
    *,
    code: int,
    fragment: str,
) -> None:
    assert error.code == code
    assert fragment in error.message


def test_validate_candidate_request_accepts_stateless_list_request() -> None:
    request = candidate_request()

    validated = validate_candidate_request(candidate_headers(), request)

    assert validated.method == "tools/list"
    assert validated.name is None
    assert validated.request_id == 1


def test_validate_candidate_request_requires_jsonrpc_2_0() -> None:
    request = candidate_request()
    request["jsonrpc"] = "1.0"

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(candidate_headers(), request)

    assert_protocol_error(raised.value, code=-32600, fragment="jsonrpc")


@pytest.mark.parametrize("request_id", [None, True, 1.5, {"nested": "id"}])
def test_validate_candidate_request_requires_a_json_rpc_request_id(request_id: object) -> None:
    request = candidate_request(request_id=request_id)

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(candidate_headers(), request)

    assert_protocol_error(raised.value, code=-32600, fragment="id")


def test_validate_candidate_request_requires_candidate_protocol_version() -> None:
    headers = candidate_headers()
    headers["MCP-Protocol-Version"] = "2025-11-25"

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(headers, candidate_request())

    assert_protocol_error(raised.value, code=-32022, fragment="Unsupported protocol version")


def test_validate_candidate_request_rejects_header_body_protocol_mismatch() -> None:
    request = candidate_request()
    request["params"]["_meta"]["io.modelcontextprotocol/protocolVersion"] = "2025-11-25"  # type: ignore[index]

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(candidate_headers(), request)

    assert_protocol_error(raised.value, code=-32020, fragment="protocol version")


def test_validate_candidate_request_requires_client_capabilities() -> None:
    request = candidate_request()
    del request["params"]["_meta"]["io.modelcontextprotocol/clientCapabilities"]  # type: ignore[index]

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(candidate_headers(), request)

    assert_protocol_error(raised.value, code=-32021, fragment="clientCapabilities")


def test_validate_candidate_request_rejects_session_header() -> None:
    headers = candidate_headers()
    headers["Mcp-Session-Id"] = "legacy-session"

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(headers, candidate_request())

    assert_protocol_error(raised.value, code=-32020, fragment="Mcp-Session-Id")


def test_validate_candidate_request_requires_matching_method_header() -> None:
    headers = candidate_headers("resources/list")

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(headers, candidate_request("tools/list"))

    assert_protocol_error(raised.value, code=-32020, fragment="Mcp-Method")


@pytest.mark.parametrize(
    ("method", "params", "name"),
    [
        ("tools/call", {"name": "kicad_help", "arguments": {}}, "kicad_help"),
        ("prompts/get", {"name": "review_board"}, "review_board"),
        ("resources/read", {"uri": "kicad://project/current"}, "kicad://project/current"),
    ],
)
def test_validate_candidate_request_requires_matching_name_header(
    method: str,
    params: dict[str, object],
    name: str,
) -> None:
    request = candidate_request(method, params=params)

    validated = validate_candidate_request(candidate_headers(method, name=name), request)

    assert validated.name == name


def test_validate_candidate_request_decodes_base64_name_header() -> None:
    request = candidate_request(
        "resources/read",
        params={"uri": "kicad://project/ölçüm"},
    )
    headers = candidate_headers(
        "resources/read",
        name="=?base64?a2ljYWQ6Ly9wcm9qZWN0L8O2bMOnw7xt?=",
    )

    validated = validate_candidate_request(headers, request)

    assert validated.name == "kicad://project/ölçüm"


def test_validate_candidate_request_rejects_legacy_initialization_methods() -> None:
    request = candidate_request("initialize")

    with pytest.raises(ProtocolValidationError) as raised:
        validate_candidate_request(candidate_headers("initialize"), request)

    assert_protocol_error(raised.value, code=-32601, fragment="not available")


def test_candidate_discovery_uses_no_unimplemented_extensions() -> None:
    result = candidate_discover_result(server_version="3.28.0")

    assert result["resultType"] == "complete"
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["capabilities"] == {
        "tools": {},
        "prompts": {},
        "resources": {},
        "extensions": {},
    }
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "kicad-mcp-pro",
        "version": "3.28.0",
    }
    assert result["ttlMs"] == 3_600_000
    assert result["cacheScope"] == "private"
    assert "KiCad" in result["instructions"]


def test_stable_sdk_request_removes_candidate_only_metadata_without_mutating_input() -> None:
    request = candidate_request(
        "tools/call",
        params={"name": "kicad_help", "arguments": {}, "requestState": "resume-1"},
    )
    original = deepcopy(request)

    translated = stable_sdk_request(request)

    assert request == original
    assert translated["params"] == {
        "name": "kicad_help",
        "arguments": {},
        "requestState": "resume-1",
    }


def test_decorate_candidate_response_adds_result_and_private_cache_metadata() -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": [
                {"name": "zeta", "inputSchema": {"type": "object"}},
                {"name": "alpha", "inputSchema": {"type": "object"}},
            ]
        },
    }
    original = deepcopy(response)

    decorated = decorate_candidate_response("tools/list", response, server_version="3.28.0")

    assert response == original
    assert [tool["name"] for tool in decorated["result"]["tools"]] == ["alpha", "zeta"]
    assert decorated["result"]["resultType"] == "complete"
    assert decorated["result"]["ttlMs"] == 300_000
    assert decorated["result"]["cacheScope"] == "private"
    assert decorated["result"]["_meta"]["io.modelcontextprotocol/serverInfo"] == {
        "name": "kicad-mcp-pro",
        "version": "3.28.0",
    }


def test_decorate_candidate_response_marks_resource_reads_private() -> None:
    response = {
        "jsonrpc": "2.0",
        "id": 2,
        "result": {"contents": [{"uri": "kicad://project/current", "text": "secret"}]},
    }

    decorated = decorate_candidate_response("resources/read", response, server_version="3.28.0")

    assert decorated["result"]["ttlMs"] == 60_000
    assert decorated["result"]["cacheScope"] == "private"


def test_decorate_candidate_response_does_not_modify_errors() -> None:
    response = {"jsonrpc": "2.0", "id": 2, "error": {"code": -32601, "message": "missing"}}

    assert decorate_candidate_response("tools/call", response, server_version="3.28.0") == response


def test_jsonrpc_error_response_preserves_request_id_and_candidate_error_data() -> None:
    error = ProtocolValidationError(
        -32020,
        "Header mismatch",
        data={"header": "Mcp-Method"},
    )

    response = jsonrpc_error_response(error, request_id="req-7")

    assert response == {
        "jsonrpc": "2.0",
        "id": "req-7",
        "error": {
            "code": -32020,
            "message": "Header mismatch",
            "data": {"header": "Mcp-Method"},
        },
    }
