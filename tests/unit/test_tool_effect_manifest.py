from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kicad_mcp.capabilities import all_records
from kicad_mcp.operating_modes import OperatingMode
from kicad_mcp.server import build_server
from kicad_mcp.tool_effect_manifest import REVIEWED_TOOL_EFFECTS
from kicad_mcp.tools.metadata import is_tool_idempotent
from kicad_mcp.tools.router import available_profiles
from scripts.build_tool_effect_manifest import MANIFEST_PATH, build, render

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = (
    ROOT / "packages" / "protocol-schemas" / "schemas" / "tool-effect-manifest.schema.json"
)


def _declared_input_schemas() -> dict[str, dict[str, object]]:
    schemas: dict[str, dict[str, object]] = {}
    for profile in available_profiles():
        server = build_server(profile)
        server.operating_mode = OperatingMode.EXPERIMENTAL
        server.allow_experimental_tools = True
        server.filter_runtime_tools = False
        for tool in server.list_tools_sync():
            schemas.setdefault(tool.name, dict(tool.input_schema or {}))
    return schemas


def test_committed_tool_effect_manifest_is_deterministic_and_schema_valid() -> None:
    manifest = build()
    assert MANIFEST_PATH.read_text(encoding="utf-8") == render(manifest)

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)


def test_reviewed_effect_contracts_match_current_public_input_schemas() -> None:
    schemas = _declared_input_schemas()
    for contract in REVIEWED_TOOL_EFFECTS:
        assert contract.name in schemas
        properties = schemas[contract.name].get("properties", {})
        assert isinstance(properties, dict)
        assert set(properties) == set(contract.arguments), contract.name


def test_reviewed_metadata_facts_match_capability_registry() -> None:
    records = all_records()
    for contract in REVIEWED_TOOL_EFFECTS:
        record = records[contract.name]
        assert record.supports_dry_run is contract.supports_dry_run
        assert record.supports_rollback is contract.supports_rollback
        assert is_tool_idempotent(contract.name) is contract.idempotent


def test_reviewed_contracts_are_fail_closed_and_internally_consistent() -> None:
    seen: set[str] = set()
    changing = {"write", "create", "delete"}
    for contract in REVIEWED_TOOL_EFFECTS:
        assert contract.name not in seen
        seen.add(contract.name)
        assert contract.effects or contract.path_arguments
        assert len(set(contract.arguments)) == len(contract.arguments)
        assert contract.destructive is bool(
            changing.intersection(contract.effects)
            or any(changing.intersection(path.effects) for path in contract.path_arguments)
        )
        path_names = {path.argument for path in contract.path_arguments}
        for path in contract.path_arguments:
            assert path.argument in contract.arguments
            if path.base_argument is not None:
                assert path.base_argument in contract.arguments
                assert path.base_argument in path_names
            if path.required:
                assert path.default is None


@pytest.mark.parametrize("field", ["unknown", "effects", "path_arguments"])
def test_manifest_schema_rejects_unknown_or_malformed_effect_facts(field: str) -> None:
    manifest = build()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    if field == "unknown":
        manifest["tools"][0]["caller_supplied_policy"] = True
    elif field == "effects":
        manifest["tools"][0]["effects"] = ["chown"]
    else:
        manifest["tools"][0]["path_arguments"] = [
            {"argument": "sheet_file", "effects": [], "required": False}
        ]

    assert not validator.is_valid(manifest)
