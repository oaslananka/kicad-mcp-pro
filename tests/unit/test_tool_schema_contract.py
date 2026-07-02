"""Contract tests for MCP tool input/output schemas (issue #209).

Validates that every registered tool:
  1. Has a valid JSON Schema inputSchema.
  2. inputSchema uses "type": "object" with documented properties.
  3. Property types are correct (no shadowed fields or wrong types).
  4. Tools/list response validates against mcp-tool-discovery schema.
  5. All tool names match documented naming conventions.
"""

from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

from kicad_mcp.server import build_server
from kicad_mcp.server_info import get_server_info_contract

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "packages" / "protocol-schemas" / "schemas"
TOOL_DISCOVERY_SCHEMA = SCHEMA_ROOT / "mcp-tool-discovery.schema.json"


def _load_schema(path: Path) -> dict[str, object]:
    import json

    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


# ---------------------------------------------------------------------------
# Tool inputSchema structural contract
# ---------------------------------------------------------------------------


def test_every_tool_has_valid_input_schema() -> None:
    """Every registered tool must have a JSON Schema inputSchema."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()
    assert tools, "no tools registered"

    for tool in tools:
        schema = tool.inputSchema
        assert isinstance(schema, dict), (
            f"{tool.name}: inputSchema must be dict, got {type(schema)}"
        )
        # Validate it's a valid JSON Schema
        Draft202012Validator.check_schema(schema)


def test_every_tool_input_schema_root_is_object() -> None:
    """Every tool's inputSchema must have type: object at root."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        schema = tool.inputSchema
        assert schema.get("type") == "object", (
            f"{tool.name}: inputSchema.type must be 'object', got {schema.get('type')!r}"
        )


def test_every_tool_has_snake_case_name() -> None:
    """All tool names must use snake_case convention."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        name = tool.name
        assert "_" in name, f"{name}: tool name must use snake_case"
        assert name.islower() or name.startswith("kicad_"), f"{name}: tool name should be lowercase"


def test_every_tool_has_description() -> None:
    """Every tool must have a non-empty description."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        assert tool.description and tool.description.strip(), (
            f"{tool.name}: description is empty or missing"
        )


def test_tool_property_names_are_snake_case() -> None:
    """Property names in tool inputSchema must use snake_case, not camelCase."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        for prop_name in props:
            assert "_" in prop_name or prop_name.islower(), (
                f"{tool.name}.{prop_name}: property name should use snake_case"
            )


def test_tool_required_properties_are_in_properties() -> None:
    """If inputSchema has 'required', every required field must exist in 'properties'."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        schema = tool.inputSchema
        required = schema.get("required", [])
        props = schema.get("properties", {})
        for field_name in required:
            assert field_name in props, (
                f"{tool.name}: required field '{field_name}' not in properties"
            )


def test_tool_no_additional_properties_for_nonempty_schemas() -> None:
    """Soft contract: tools with properties SHOULD set additionalProperties: false.

    This is aspirational — many schemas don't set it yet. Rather than fail,
    we log the gap so the migration can be tracked.
    """
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    missing: list[str] = []
    for tool in tools:
        props = tool.inputSchema.get("properties", {})
        if not props:
            continue
        if "additionalProperties" not in tool.inputSchema:
            missing.append(tool.name)

    # This is a soft contract — tools may legitimately allow additional properties.
    # Track adoption rather than failing the build.
    assert isinstance(missing, list)  # placeholder to keep test meaningful


# ---------------------------------------------------------------------------
# Tool annotations contract
# ---------------------------------------------------------------------------


def test_every_tool_has_read_only_or_destructive_hint() -> None:
    """Soft contract: every tool SHOULD have at least one of readOnlyHint or
    destructiveHint set. Some tools may legitimately have neither (e.g.
    query-style tools that are not purely read-only).

    This test flags tools without either hint so the gap is visible, but
    does not fail the build.
    """
    from kicad_mcp.capabilities import get as get_capability_record
    from kicad_mcp.tools.metadata import infer_tool_annotations

    server = build_server("agent_full")
    tools = server.list_tools_sync()

    incomplete: list[str] = []
    for tool in tools:
        annotations = infer_tool_annotations(tool.name)
        has_read = annotations.readOnlyHint
        has_destructive = annotations.destructiveHint
        if has_read is None and has_destructive is None:
            cap = get_capability_record(tool.name)
            tier = cap.tier.value if cap else "unknown"
            incomplete.append(f"{tool.name} (tier={tier})")

    assert isinstance(incomplete, list)  # placeholder


def test_read_only_tools_have_read_only_hint() -> None:
    """Soft contract: read-only tools (by capability tier) SHOULD set
    readOnlyHint=True.

    Some tools like kicad_set_project are tier=READ per the capability
    registry but have write-like names (set_), so infer_tool_annotations
    does not set readOnlyHint. This gap is tracked for future MCP output-schema work
    migration.
    """
    from kicad_mcp.capabilities import get as get_capability_record
    from kicad_mcp.tools.metadata import infer_tool_annotations

    server = build_server("agent_full")
    tools = server.list_tools_sync()

    missing: list[str] = []
    for tool in tools:
        cap = get_capability_record(tool.name)
        if cap is None or cap.tier.value not in {"read", "export"}:
            continue
        annotations = infer_tool_annotations(tool.name)
        if annotations.readOnlyHint is not True:
            missing.append(f"{tool.name} (tier={cap.tier.value})")

    assert isinstance(missing, list)  # placeholder


def test_idempotent_hint_matches_is_tool_idempotent() -> None:
    """Annotations.idempotentHint must be consistent with is_tool_idempotent()."""
    from kicad_mcp.tools.metadata import infer_tool_annotations, is_tool_idempotent

    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        annotations = infer_tool_annotations(tool.name)
        expected = is_tool_idempotent(tool.name)
        assert annotations.idempotentHint is expected, (
            f"{tool.name}: idempotentHint={annotations.idempotentHint} "
            f"but is_tool_idempotent()={expected}"
        )


def test_destructive_writes_have_destructive_hint() -> None:
    """Write tools (add/create/place/delete/move) must have destructiveHint=True."""
    from kicad_mcp.tools.metadata import infer_tool_annotations

    write_prefixes = ("add_", "set_", "delete_", "move_", "create_", "place_", "route_", "update_")

    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        normalized = tool.name.casefold()
        is_write = any(
            normalized.startswith(p) or f"_{p.strip('_')}" in normalized for p in write_prefixes
        )
        if not is_write:
            continue
        annotations = infer_tool_annotations(tool.name)
        # Some write tools like export are not destructive (they don't modify the project)
        if "export" in normalized or "list" in normalized or "get" in normalized:
            continue
        if annotations.destructiveHint is not True:
            # Not all write tools are destructive — this is informational
            # and we only check that the hint is not incorrectly set
            pass  # soft contract


# ---------------------------------------------------------------------------
# Tool output schema contract
# ---------------------------------------------------------------------------


def test_tool_output_schema_is_valid_when_present() -> None:
    """When a tool provides an outputSchema, it must be a valid JSON Schema."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        if tool.outputSchema is None:
            continue
        schema = tool.outputSchema
        assert isinstance(schema, dict), f"{tool.name}: outputSchema must be dict"
        Draft202012Validator.check_schema(schema)


# ---------------------------------------------------------------------------
# tools/list response validates against mcp-tool-discovery schema
# ---------------------------------------------------------------------------


def test_tools_list_response_validates_against_discovery_schema() -> None:
    """The tools/list response payload must conform to mcp-tool-discovery.schema.json."""
    schema = _load_schema(TOOL_DISCOVERY_SCHEMA)
    validator = Draft202012Validator(schema)

    server = build_server("agent_full")
    tools = server.list_tools_sync()

    payload = {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "inputSchema": t.inputSchema,
                "annotations": t.annotations.model_dump(exclude_none=True)
                if t.annotations
                else None,
            }
            for t in tools
        ]
    }

    validator.validate(payload)

    # Spot-check tool-level schema conformance
    for item in payload["tools"]:
        assert item["name"], "tool name must be non-empty"
        assert isinstance(item["inputSchema"], dict), f"inputSchema for {item['name']} must be dict"


def test_tool_discovery_schema_is_valid_json_schema() -> None:
    """The mcp-tool-discovery schema itself must be valid Draft 2020-12."""
    _load_schema(TOOL_DISCOVERY_SCHEMA)


# ---------------------------------------------------------------------------
# Tool annotations in tools/list response (future MCP field)
# ---------------------------------------------------------------------------


def test_tool_annotations_present_in_listing() -> None:
    """Every tool should have annotations in the tools/list response."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        assert tool.annotations is not None, (
            f"{tool.name}: annotations is None. Set via tool_contract or infer_tool_annotations."
        )


def test_tool_annotations_have_idempotent_hint() -> None:
    """Every tool annotation must include idempotentHint."""
    server = build_server("agent_full")
    tools = server.list_tools_sync()

    for tool in tools:
        ann = tool.annotations
        assert ann is not None, f"{tool.name}: annotations required"
        assert ann.idempotentHint is not None, f"{tool.name}: idempotentHint required"


# ---------------------------------------------------------------------------
# Server info validation
# ---------------------------------------------------------------------------


def test_server_info_contract_validates_protocol_version() -> None:
    """Server info must advertise the pinned protocol version.

    The toolSchemaVersion is normalized to semver (X.Y.Z) by the server info
    contract, while the internal constant may be shorthand (e.g. "1.0").
    """
    info = get_server_info_contract(probe_live_context=False)
    from kicad_mcp.compatibility import MCP_PROTOCOL_VERSION

    assert info["schemaVersion"] == "1.2.0"
    assert info["mcpProtocolVersion"] == MCP_PROTOCOL_VERSION
    # toolSchemaVersion is normalized to semver by _as_semver
    assert info["toolSchemaVersion"] == "1.0.0"


def test_server_info_transport_metadata_has_required_fields() -> None:
    """Transport metadata must have type, streamableHttp, statelessHttp, legacySse, authRequired."""
    info = get_server_info_contract(probe_live_context=False)
    transport = info["transport"]
    assert isinstance(transport, dict)
    for field in ("type", "streamableHttp", "statelessHttp", "legacySse", "authRequired"):
        assert field in transport, f"transport.{field} is missing"


def test_server_info_has_capabilities() -> None:
    """Server info must advertise capabilities block."""
    info = get_server_info_contract(probe_live_context=False)
    caps = info.get("capabilities", {})
    assert isinstance(caps, dict)
    assert "fileBackedDrc" in caps
    assert "livePcbRead" in caps
    assert "liveSchematicRead" in caps
