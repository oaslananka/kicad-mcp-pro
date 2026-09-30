from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from kicad_mcp.capabilities import all_protocol_metadata, metadata_coverage

SCHEMA_ROOT = Path(__file__).resolve().parents[2] / "packages" / "protocol-schemas" / "schemas"

REQUIRED_SCHEMA_FILES = {
    "bom-netlist-summary.schema.json",
    "compatibility-manifest.schema.json",
    "extension-active-context.schema.json",
    "kicad-mcp-server-info.schema.json",
    "mcp-server-health.schema.json",
    "mcp-tool-capability.schema.json",
    "mcp-tool-discovery.schema.json",
    "normalized-diagnostic.schema.json",
    "tool-effect-manifest.schema.json",
}


def _load_schema(name: str) -> dict[str, object]:
    schema = json.loads((SCHEMA_ROOT / name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def test_protocol_schema_package_exposes_required_contracts() -> None:
    schema_files = {path.name for path in SCHEMA_ROOT.glob("*.schema.json")}

    assert schema_files == REQUIRED_SCHEMA_FILES
    for schema_file in REQUIRED_SCHEMA_FILES:
        schema = _load_schema(schema_file)
        assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert schema["x-kicad-mcp"]["trackingIssue"] == "OASLANA-52"


def test_advertised_tool_metadata_matches_shared_capability_schema() -> None:
    schema = _load_schema("mcp-tool-capability.schema.json")
    validator = Draft202012Validator(schema)
    metadata = all_protocol_metadata()

    assert metadata
    for record in metadata:
        validator.validate(record)

    by_name = {record["name"]: record for record in metadata}
    assert by_name["export_manufacturing_package"]["human_gate_required"] is True
    assert by_name["export_manufacturing_package"]["maturity"] == "stable"
    assert by_name["sch_render_png"]["runtime"] == "none"
    assert by_name["sch_render_png"]["writes_files"] is True
    assert by_name["lib_search_components"]["runtime"] == "network"


def test_router_tools_have_capability_metadata_coverage() -> None:
    coverage = metadata_coverage()

    assert coverage["coverage_pct"] == 100.0
    assert coverage["missing_tools"] == []
