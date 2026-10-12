"""Lint public MCP tool contracts against router and metadata conventions."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from kicad_mcp.capabilities import AccessTier, CapabilityRecord, all_records, metadata_coverage
from kicad_mcp.operating_modes import OperatingMode
from kicad_mcp.server import build_server
from kicad_mcp.tool_effect_manifest import REVIEWED_TOOL_EFFECTS
from kicad_mcp.tools.metadata import is_tool_idempotent
from kicad_mcp.tools.router import available_profiles


async def _tool_schemas() -> dict[str, dict[str, Any]]:
    server = build_server("full")
    return {tool.name: dict(tool.input_schema or {}) for tool in await server.list_tools()}


async def _declared_tool_schemas() -> dict[str, dict[str, Any]]:
    """Return every tool schema any declared profile can surface.

    ``build_server("full")`` alone is not enough: its listing is narrowed twice
    more, by the default read-only operating mode and by the runtime IPC filter,
    so no mutating tool reaches a schema check on a machine without KiCad
    running. Both narrowings are lifted here on purpose -- a schema is a static
    contract, and a host that never sees a tool today will see it the moment the
    operator switches modes.
    """
    schemas: dict[str, dict[str, Any]] = {}
    for profile in available_profiles():
        server = build_server(profile)
        server.operating_mode = OperatingMode.EXPERIMENTAL
        server.allow_experimental_tools = True
        server.filter_runtime_tools = False
        for tool in await server.list_tools():
            schemas.setdefault(tool.name, dict(tool.input_schema or {}))
    return schemas


def _schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.get("properties", {})
    return properties if isinstance(properties, dict) else {}


def _array_schema_paths_missing_items(node: object, path: str = "$") -> list[str]:
    """Return array-schema paths rejected by stricter MCP hosts."""
    missing: list[str] = []
    if isinstance(node, dict):
        if node.get("type") == "array" and "items" not in node:
            missing.append(path)
        for key, value in node.items():
            missing.extend(_array_schema_paths_missing_items(value, f"{path}/{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            missing.extend(_array_schema_paths_missing_items(value, f"{path}/{index}"))
    return missing


def _check_metadata_coverage(errors: list[str]) -> None:
    coverage = metadata_coverage()
    missing_tools = coverage["missing_tools"]
    if not isinstance(missing_tools, list):
        errors.append("Capability metadata coverage missing_tools must be a list.")
    elif missing_tools:
        missing = ", ".join(str(name) for name in missing_tools)
        errors.append(f"Missing capability metadata for routed tools: {missing}")


async def _check_readonly_profiles(records: dict[str, CapabilityRecord], errors: list[str]) -> None:
    for profile in {"beginner", "read_only_inspection"}:
        server = build_server(profile)
        surfaced = {tool.name for tool in await server.list_tools()}
        for tool_name in surfaced:
            record = records.get(tool_name)
            if record is None:
                continue
            if record.tier in {AccessTier.WRITE, AccessTier.PUBLISH, AccessTier.HUMAN_ONLY}:
                errors.append(f"Read-only profile '{profile}' exposes mutating tool {tool_name}")


def _check_declared_array_items(schemas: dict[str, dict[str, Any]], errors: list[str]) -> None:
    for tool_name, schema in sorted(schemas.items()):
        for path in _array_schema_paths_missing_items(schema):
            errors.append(
                f"{tool_name} input schema array at {path} must declare items "
                "for MCP host compatibility."
            )


def _check_search_compatibility(schemas: dict[str, dict[str, Any]], errors: list[str]) -> None:
    properties = _schema_properties(schemas.get("lib_search_components", {}))
    if "query" not in properties:
        errors.append("lib_search_components must expose preferred parameter 'query'.")
    if "keyword" not in properties:
        errors.append("lib_search_components must keep backward-compatible 'keyword'.")


def _check_mutation_flags(records: dict[str, CapabilityRecord], errors: list[str]) -> None:
    for name, record in records.items():
        if record.tier in {AccessTier.WRITE, AccessTier.PUBLISH, AccessTier.HUMAN_ONLY}:
            if not isinstance(record.supports_rollback, bool):
                errors.append(f"{name} must explicitly declare rollback support.")
            if not isinstance(record.supports_dry_run, bool):
                errors.append(f"{name} must explicitly declare dry-run support.")


def _check_access_tiers(records: dict[str, CapabilityRecord], errors: list[str]) -> None:
    # An agent must never mistake a GUI/file mutation for a read-only effect.
    for name, record in records.items():
        if record.tier is AccessTier.READ:
            if record.writes_files:
                errors.append(f"READ-tier tool {name} must not declare writes_files=True.")
            if record.writes_kicad_gui_state:
                errors.append(
                    f"READ-tier tool {name} must not declare writes_kicad_gui_state=True."
                )
        is_human_only = record.tier is AccessTier.HUMAN_ONLY
        if is_human_only and not record.human_gate_required:
            errors.append(f"HUMAN_ONLY tool {name} must declare human_gate_required=True.")
        if record.human_gate_required and not is_human_only:
            errors.append(
                f"{name} declares human_gate_required=True but its tier is not HUMAN_ONLY."
            )


def _check_reviewed_effects(
    records: dict[str, CapabilityRecord],
    declared_schemas: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    # Effects are authoritative only when a reviewed manifest matches metadata.
    for contract in REVIEWED_TOOL_EFFECTS:
        schema = declared_schemas.get(contract.name)
        if schema is None:
            errors.append(f"Reviewed effect tool {contract.name} is not publicly declared.")
            continue
        properties = _schema_properties(schema)
        if set(properties) != set(contract.arguments):
            errors.append(
                f"Reviewed effect contract arguments drifted for {contract.name}: "
                f"manifest={sorted(contract.arguments)}, schema={sorted(properties)}"
            )
        record = records.get(contract.name)
        if record is None:
            errors.append(f"Reviewed effect tool {contract.name} has no capability metadata.")
            continue
        if record.supports_dry_run is not contract.supports_dry_run:
            errors.append(f"Reviewed effect dry-run fact drifted for {contract.name}.")
        if record.supports_rollback is not contract.supports_rollback:
            errors.append(f"Reviewed effect rollback fact drifted for {contract.name}.")
        if is_tool_idempotent(contract.name) is not contract.idempotent:
            errors.append(f"Reviewed effect idempotency fact drifted for {contract.name}.")


async def lint() -> list[str]:
    """Return human-readable contract errors in the original deterministic order."""
    errors: list[str] = []
    _check_metadata_coverage(errors)
    records = all_records()
    await _check_readonly_profiles(records, errors)
    schemas = await _tool_schemas()
    declared_schemas = await _declared_tool_schemas()
    _check_declared_array_items(declared_schemas, errors)
    _check_search_compatibility(schemas, errors)
    _check_mutation_flags(records, errors)
    _check_access_tiers(records, errors)
    _check_reviewed_effects(records, declared_schemas, errors)
    return errors


def main() -> int:
    errors = asyncio.run(lint())
    if errors:
        print("Tool contract lint failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Tool contract lint passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
