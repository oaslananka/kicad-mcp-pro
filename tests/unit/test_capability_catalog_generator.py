"""Generated local capability contract consumed by future Cloud adapters."""

from __future__ import annotations

import hashlib
import json

import scripts.build_capability_catalog as builder
from kicad_mcp.tools.router import TOOL_CATEGORIES


def test_catalog_is_derived_from_actual_registered_router_tools() -> None:
    data = builder.build()
    expected = {name for group in TOOL_CATEGORIES.values() for name in group["tools"]}
    tools = data["tools"]
    names = [tool["name"] for tool in tools]
    assert names == sorted(expected)
    assert len(names) == len(set(names))
    assert len(data["categories"]) == len(TOOL_CATEGORIES)
    assert {category["name"] for category in data["categories"]} == set(TOOL_CATEGORIES)
    assert all(tool["category"] in TOOL_CATEGORIES for tool in tools)
    assert all(tool["inputSchema"]["type"] == "object" for tool in tools)


def test_catalog_is_explicitly_not_an_unapproved_cloud_execution_grant() -> None:
    data = builder.build()
    by_name = {tool["name"]: tool for tool in data["tools"]}
    assert data["schemaVersion"] == "1.0.0"
    assert all(tool["remoteCallable"] is False for tool in data["tools"])
    assert all(tool["capability"]["tested_kicad_versions"] for tool in data["tools"])
    assert all(tool["capability"]["tier"] for tool in data["tools"])
    assert all(tool["capability"]["maturity"] for tool in data["tools"])
    assert all(tool["capability"]["runtime"] for tool in data["tools"])
    assert by_name["pcb_delete_items"]["capability"]["tier"] == "write"
    assert by_name["kicad_set_project"]["remoteCallable"] is False


def test_committed_catalog_is_deterministic_and_drift_checked() -> None:
    data = builder.build()
    assert builder.MANIFEST_PATH.read_text(encoding="utf-8") == builder.render(data)
    assert builder.main(["--check"]) == 0
    assert json.loads(builder.render(data)) == data


def test_manifest_check_rejects_missing_or_stale_output(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(builder, "MANIFEST_PATH", missing)
    assert builder.main(["--check"]) == 1
    missing.write_text('{"schemaVersion":"wrong"}', encoding="utf-8")
    assert builder.main(["--check"]) == 1


def test_revision_is_stable_digest_of_registered_tool_contracts() -> None:
    data = builder.build()
    serialized = json.dumps(
        data["tools"], ensure_ascii=False, separators=(",", ":"), sort_keys=True
    )
    assert data["catalogRevision"] == hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_runtime_catalog_revision_matches_generated_artifact() -> None:
    from kicad_mcp.runtime_capability_catalog import build_local_catalog_entries, catalog_revision

    entries = build_local_catalog_entries()
    data = builder.build()
    assert entries == data["tools"]
    assert catalog_revision(entries) == data["catalogRevision"]
