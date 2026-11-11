"""Package-runtime view of the same registered MCP tools used by the build artifact.

This is static discovery only: it does not authorize any remote operation.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from functools import lru_cache
from typing import Any, cast

from .capabilities import all_records, to_protocol_metadata
from .operating_modes import OperatingMode
from .tools.router import TOOL_CATEGORIES


def build_local_catalog_entries() -> list[dict[str, Any]]:
    """Return registered tool contracts, independent of the local KiCad GUI."""
    from .server import build_server

    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        # MCPServer is extended at runtime with profile/availability helpers.
        server = cast(Any, build_server("expert"))
    server.operating_mode = OperatingMode.EXPERIMENTAL
    server.allow_experimental_tools = True
    server.filter_runtime_tools = False
    registered_tools = sorted(server.list_tools_sync(), key=lambda item: item.name)
    registered_names = [tool.name for tool in registered_tools]
    if len(set(registered_names)) != len(registered_names):
        raise ValueError("Duplicate tool name in registered MCP server")

    categories: dict[str, str] = {}
    for category, details in TOOL_CATEGORIES.items():
        for name in details["tools"]:
            if name in categories:
                raise ValueError(f"Tool {name} belongs to multiple router categories")
            categories[name] = category

    if set(registered_names) != set(categories):
        raise ValueError(
            "Registered MCP tools do not match router declarations: "
            f"missing={sorted(set(categories) - set(registered_names))}, "
            f"extra={sorted(set(registered_names) - set(categories))}"
        )
    records = all_records()
    entries: list[dict[str, Any]] = []
    for tool in registered_tools:
        capability = records.get(tool.name)
        if capability is None:
            raise ValueError(f"Missing capability metadata: {tool.name}")
        schema = dict(tool.input_schema or {})
        if schema.get("type") != "object":
            raise ValueError(f"Invalid MCP input object schema: {tool.name}")
        entries.append(
            {
                "name": tool.name,
                "category": categories[tool.name],
                "description": tool.description or "",
                "inputSchema": schema,
                "capability": to_protocol_metadata(capability),
                # Local capability existence never implies Cloud reachability.
                "remoteCallable": False,
            }
        )

    return entries


def catalog_revision(entries: list[dict[str, Any]]) -> str:
    """Stable SHA-256 of the complete registered input/effect contract."""
    return hashlib.sha256(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()


@lru_cache(maxsize=1)
def installed_catalog_revision() -> str:
    """Compute the installed local tool revision only when explicitly requested."""
    return catalog_revision(build_local_catalog_entries())
