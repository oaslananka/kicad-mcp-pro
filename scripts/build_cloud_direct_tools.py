"""Generate independently reviewable Cloud MCP pilot tools from the local registry.

No tool is remotely authorized by generation: the private owner Connector
enforces project, client, local tool availability and signed write consent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "integrations/common/capability-catalog.json"
OUTPUT = ROOT / "apps/cloud/src/cloud-direct-tool-contracts.generated.ts"

# New local tools remain private until an explicit review adds them here.
PILOT_NAMES = (
    "kicad_get_version",
    "pcb_get_board_summary",
    "pcb_get_footprints",
    "pcb_save",
    "run_drc",
    "run_erc",
    "sch_get_symbols",
    "sch_get_wires",
    "sch_move_symbol",
)
# These two beta writes were individually reviewed for the first remote pilot.
REVIEWED_BETA_NAMES = frozenset({"pcb_save", "sch_move_symbol"})
PROJECT_ID_SCHEMA = {
    "type": "string",
    "format": "uuid",
    "description": "Granted Cloud project UUID; optional when exactly one is accessible",
}
DENIED_PARTS = ("manufactur", "mfg_", "jobset_", "signoff", "release_gate")
DENIED_NAMES = {
    "kicad_set_project",
    "kicad_create_new_project",
    "kicad_init",
    "project_set_project",
    "project_open",
}


def _is_reviewable_pilot_tool(
    name: str, item: dict[str, object], capability: dict[str, object], schema: dict[str, object]
) -> bool:
    tier = capability.get("tier")
    maturity = capability.get("maturity")
    if (
        tier not in {"read", "write"}
        or maturity not in {"stable", "beta"}
        or (maturity == "beta" and (name not in REVIEWED_BETA_NAMES or tier != "write"))
        or item.get("remoteCallable") is not False
        or name in DENIED_NAMES
        or name.startswith(("vcs_restore_", "project_import_", "pcb_import_"))
        or any(part in name for part in DENIED_PARTS)
    ):
        return False
    if (
        capability.get("human_gate_required") is not False
        or capability.get("requires_human_confirmation") is not False
    ):
        return False
    if tier == "read" and (
        capability.get("writes_files") is not False
        or capability.get("writes_kicad_gui_state") is not False
    ):
        return False
    properties = schema.get("properties", {})
    return (
        schema.get("type") == "object"
        and isinstance(properties, dict)
        and "project_id" not in properties
    )


def _index_catalog_tools(catalog: dict[str, object]) -> dict[str, dict[str, object]]:
    raw = catalog.get("tools")
    if not isinstance(raw, list):
        raise ValueError("Local capability catalog must contain a tools array")
    indexed = {item["name"]: item for item in raw if isinstance(item, dict) and "name" in item}
    if len(indexed) != len(raw):
        raise ValueError("Duplicate or malformed local tool records")
    return indexed


def _build_pilot_tool(name: str, indexed: dict[str, dict[str, object]]) -> dict[str, object]:
    item = indexed.get(name)
    if item is None:
        raise ValueError(f"Selected pilot tool is missing: {name}")
    capability = item.get("capability")
    schema = item.get("inputSchema")
    if not isinstance(capability, dict) or not isinstance(schema, dict):
        raise ValueError(f"Invalid registered tool contract: {name}")
    if not _is_reviewable_pilot_tool(name, item, capability, schema):
        raise ValueError(f"Tool requires a separate security review: {name}")

    is_read = capability["tier"] == "read"
    return {
        "name": name,
        "description": item.get("description") or "",
        "accessMode": "readonly" if is_read else "write",
        "maturity": capability["maturity"],
        "inputSchema": schema,
        "annotations": {
            "readOnlyHint": is_read,
            "destructiveHint": not is_read,
            "idempotentHint": is_read,
            "openWorldHint": False,
        },
        "securitySchemes": [
            {
                "type": "oauth2",
                "scopes": ["projects:read"] if is_read else ["projects:read", "projects:write"],
            }
        ],
    }


def build(catalog: dict[str, object]) -> list[dict[str, object]]:
    indexed = _index_catalog_tools(catalog)
    tools = (_build_pilot_tool(name, indexed) for name in PILOT_NAMES)
    return sorted(tools, key=lambda entry: entry["name"])


def render(
    tools: list[dict[str, object]],
    project_id_schema: dict[str, str] | None = None,
) -> str:
    project_schema = project_id_schema or PROJECT_ID_SCHEMA
    contract = {"projectIdSchema": project_schema, "tools": tools}
    encoded = json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    revision = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    project_schema_source = json.dumps(project_schema, ensure_ascii=False, indent=2, sort_keys=True)
    readable = json.dumps(tools, ensure_ascii=False, indent=2, sort_keys=True)
    return (
        "// Generated by scripts/build_cloud_direct_tools.py; do not hand-edit.\n"
        "// Reviewed pilot metadata only; execution needs signed local authorization.\n"
        f"export const CLOUD_PROJECT_ID_SCHEMA = {project_schema_source} as const;\n"
        f'export const CLOUD_DIRECT_TOOL_REVISION = "{revision}";\n'
        f"export const CLOUD_DIRECT_TOOLS = {readable} as const;\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generated = render(build(json.loads(LOCAL.read_text(encoding="utf-8"))))
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != generated:
            print(
                "Cloud direct tool contract drift: regenerate published pilot metadata",
                file=sys.stderr,
            )
            return 1
        print("Cloud direct tool contract OK")
        return 0
    OUTPUT.write_text(generated, encoding="utf-8", newline="\n")
    print("Generated independent Cloud MCP pilot tool metadata")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
