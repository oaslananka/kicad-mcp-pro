"""Generate the versioned local MCP capability catalog from *registered* tools.

This static contract is discovery metadata, not a remote execution grant.
Cloud adapters must separately prove that a tool is executable, in-scope,
supported by the current KiCad runtime, and authorized for the caller.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

from kicad_mcp.runtime_capability_catalog import build_local_catalog_entries, catalog_revision
from kicad_mcp.tools.router import TOOL_CATEGORIES

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "integrations" / "common" / "capability-catalog.json"
SCHEMA_VERSION = "1.0.0"


def build() -> dict[str, Any]:
    """Capture the actual expert registry without requiring live KiCad/IPC."""
    entries = build_local_catalog_entries()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        "schemaVersion": SCHEMA_VERSION,
        "catalogRevision": catalog_revision(entries),
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
