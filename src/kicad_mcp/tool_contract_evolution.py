"""Classify changes to the generated MCP tool contract before Cloud publication.

This is an offline compatibility audit; it does not grant remote execution rights.
Potentially breaking changes must be reviewed before altering a published
remote MCP tool definition.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_SAFETY_FIELDS = (
    "tier",
    "human_gate_required",
    "requires_human_confirmation",
    "writes_files",
    "writes_kicad_gui_state",
)


def _tools(catalog: Mapping[str, object]) -> dict[str, Mapping[str, Any]]:
    entries = catalog.get("tools")
    if not isinstance(entries, list):
        raise ValueError("Tool catalog must contain a tools array")
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in entries:
        if not isinstance(item, dict):
            raise ValueError("Tool catalog contains an invalid entry")
        name = item.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("Tool catalog contains a missing tool name")
        if name in indexed:
            raise ValueError(f"Duplicate tool name: {name}")
        if not isinstance(item.get("inputSchema"), dict):
            raise ValueError(f"Tool {name} must declare an input object schema")
        indexed[name] = item
    return indexed


def _potentially_breaking_input_schema(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """Conservatively flag changes beyond extra optional input properties."""
    if before.get("type") != after.get("type"):
        return True
    original_required = set(before.get("required") or [])
    updated_required = set(after.get("required") or [])
    if updated_required - original_required:
        return True
    original_properties = before.get("properties") or {}
    updated_properties = after.get("properties") or {}
    if not isinstance(original_properties, dict) or not isinstance(updated_properties, dict):
        return True
    for name, original in original_properties.items():
        if name not in updated_properties or original != updated_properties[name]:
            return True
    ignored = {"properties", "required", "title", "description"}
    return any(before.get(key) != after.get(key) for key in (set(before) | set(after)) - ignored)


def _potentially_breaking_tool(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    if before.get("remoteCallable") != after.get("remoteCallable"):
        return True
    old_capability = before.get("capability")
    new_capability = after.get("capability")
    if not isinstance(old_capability, dict) or not isinstance(new_capability, dict):
        return True
    if any(old_capability.get(field) != new_capability.get(field) for field in _SAFETY_FIELDS):
        return True
    old_schema = before.get("inputSchema")
    new_schema = after.get("inputSchema")
    if not isinstance(old_schema, dict) or not isinstance(new_schema, dict):
        return True
    return _potentially_breaking_input_schema(old_schema, new_schema)


def compare_tool_catalogs(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, list[str]]:
    """Return added/removed/changed tools and conservative compatibility hazards.

    A tool in 'breaking' is not automatically rejected: a deliberate, reviewed
    retirement or migration may still be appropriate. Additions are never
    silently published by this comparison.
    """
    previous = _tools(before)
    current = _tools(after)
    old_names = set(previous)
    new_names = set(current)
    common = old_names & new_names
    removed = old_names - new_names
    return {
        "added": sorted(new_names - old_names),
        "removed": sorted(removed),
        "changed": sorted(name for name in common if previous[name] != current[name]),
        "breaking": sorted(
            removed
            | {name for name in common if _potentially_breaking_tool(previous[name], current[name])}
        ),
    }
