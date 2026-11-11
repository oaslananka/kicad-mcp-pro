"""Generate the versioned local MCP capability catalog from *registered* tools.

This static contract is discovery metadata, not a remote execution grant.
Cloud adapters must separately prove that a tool is executable, in-scope,
supported by the current KiCad runtime, and authorized for the caller.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from kicad_mcp.capabilities import all_records, to_protocol_metadata
from kicad_mcp.operating_modes import OperatingMode
from kicad_mcp.server import build_server
from kicad_mcp.tools.router import TOOL_CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integrations" / "common" / "capability-catalog.json"
SCHEMA_VERSION = "1.0.0"


def build() -> dict[str, Any]:
    """Capture the actual expert registry without requiring live KiCad/IPC."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        server = build_server("expert")
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

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "catalogRevision": hashlib.sha256(
            json.dumps(entries, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(
                "utf-8"
            )
        ).hexdigest(),
        "source": {
            "repository": "oaslananka/kicad-mcp-pro",
            "registry": "src/kicad_mcp/tools/router.py",
            "packageVersion": str(project["project"]["version"]),
        },
        "categories": [
            {
                "name": name,
                "description": details["description"],
                "toolCount": len(details["tools"]),
            }
            for name, details in TOOL_CATEGORIES.items()
        ],
        "tools": entries,
    }


def render(data: dict[str, Any]) -> str:
    """Deterministic JSON with one compact tool schema per reviewable line."""

    def compact(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    lines = [
        "{",
        f'  "schemaVersion": {compact(data["schemaVersion"])},',
        f'  "catalogRevision": {compact(data["catalogRevision"])},',
        f'  "source": {compact(data["source"])},',
        f'  "categories": {compact(data["categories"])},',
        '  "tools": [',
    ]
    for index, tool in enumerate(data["tools"]):
        comma = "," if index + 1 < len(data["tools"]) else ""
        lines.append(f"    {compact(tool)}{comma}")
    lines.extend(["  ]", "}"])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate local KiCad capability catalog.")
    parser.add_argument(
        "--check", action="store_true", help="Fail if the checked-in catalog drifted."
    )
    args = parser.parse_args(argv)
    content = render(build())
    if args.check:
        if not MANIFEST_PATH.is_file() or MANIFEST_PATH.read_text(encoding="utf-8") != content:
            print(
                "Capability catalog drift: run scripts/build_capability_catalog.py", file=sys.stderr
            )
            return 1
        print("capability-catalog.json OK")
        return 0
    MANIFEST_PATH.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {MANIFEST_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
