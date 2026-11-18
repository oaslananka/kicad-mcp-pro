"""Regression tests for Cloud MCP tool metadata change detection."""

from copy import deepcopy
from typing import Any

from kicad_mcp.tool_contract_evolution import compare_tool_catalogs


def tool(
    name: str = "pcb_get_board_summary", *, schema: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "name": name,
        "description": "Read the board summary.",
        "inputSchema": schema or {"type": "object", "properties": {"detail": {"type": "string"}}},
        "capability": {"tier": "readonly"},
        "remoteCallable": False,
    }


def catalog(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"schemaVersion": "1.0.0", "catalogRevision": "example", "tools": list(entries)}


def test_new_tool_is_detected_without_blocking_existing_contract() -> None:
    result = compare_tool_catalogs(catalog(tool()), catalog(tool(), tool("run_erc")))
    assert result["added"] == ["run_erc"]
    assert result["removed"] == []
    assert result["breaking"] == []


def test_deleted_tool_is_not_silently_accepted() -> None:
    result = compare_tool_catalogs(catalog(tool()), catalog())
    assert result["removed"] == ["pcb_get_board_summary"]
    assert "pcb_get_board_summary" in result["breaking"]


def test_description_only_change_requires_review_not_breaking() -> None:
    new = tool()
    new["description"] = "Summarize the active board."
    result = compare_tool_catalogs(catalog(tool()), catalog(new))
    assert result["changed"] == ["pcb_get_board_summary"]
    assert result["breaking"] == []


def test_new_optional_argument_is_backward_compatible() -> None:
    new = tool()
    new["inputSchema"]["properties"]["format"] = {"type": "string"}
    result = compare_tool_catalogs(catalog(tool()), catalog(new))
    assert result["breaking"] == []
    assert result["changed"] == ["pcb_get_board_summary"]


def test_new_required_argument_is_flagged_as_breaking() -> None:
    new = tool()
    new["inputSchema"]["required"] = ["detail"]
    result = compare_tool_catalogs(catalog(tool()), catalog(new))
    assert result["breaking"] == ["pcb_get_board_summary"]


def test_removed_parameter_and_changed_type_are_breaking() -> None:
    removed = tool()
    removed["inputSchema"]["properties"].pop("detail")
    changed = tool()
    changed["inputSchema"]["properties"]["detail"] = {"type": "integer"}
    for candidate in (removed, changed):
        assert compare_tool_catalogs(catalog(tool()), catalog(candidate))["breaking"] == [
            "pcb_get_board_summary"
        ]


def test_permission_or_exposure_change_requires_explicit_review() -> None:
    new = deepcopy(tool())
    new["capability"]["tier"] = "write"
    assert compare_tool_catalogs(catalog(tool()), catalog(new))["breaking"] == [
        "pcb_get_board_summary"
    ]
    exposed = tool()
    exposed["remoteCallable"] = True
    result = compare_tool_catalogs(catalog(tool()), catalog(exposed))
    assert result["changed"] == ["pcb_get_board_summary"]
    assert result["breaking"] == ["pcb_get_board_summary"]


def test_no_change_has_empty_delta_and_duplicate_names_fail_closed() -> None:
    assert compare_tool_catalogs(catalog(tool()), catalog(tool())) == {
        "added": [],
        "removed": [],
        "changed": [],
        "breaking": [],
    }
    try:
        compare_tool_catalogs(catalog(tool(), tool()), catalog(tool()))
    except ValueError as error:
        assert "duplicate" in str(error).lower()
    else:
        raise AssertionError("Duplicate tool must fail")


def test_rejects_malformed_catalogs_and_duplicate_tool_names() -> None:
    invalid_catalogs = [
        {},
        {"tools": [None]},
        {"tools": [{"name": "", "inputSchema": {"type": "object"}}]},
        {"tools": [{"name": "run_drc", "inputSchema": "not-an-object"}]},
        catalog(tool(), tool()),
    ]
    for invalid in invalid_catalogs:
        try:
            compare_tool_catalogs(invalid, catalog())
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed catalog must fail closed")


def test_schema_shape_and_missing_permissions_require_review() -> None:
    cases = []
    changed_type = tool()
    changed_type["inputSchema"]["type"] = "array"
    cases.append(changed_type)
    invalid_properties = tool()
    invalid_properties["inputSchema"]["properties"] = []
    cases.append(invalid_properties)
    unknown_permissions = tool()
    unknown_permissions.pop("capability")
    cases.append(unknown_permissions)
    for changed in cases:
        assert compare_tool_catalogs(catalog(tool()), catalog(changed))["breaking"] == [
            "pcb_get_board_summary"
        ]


if __name__ == "__main__":
    for name, candidate in sorted(globals().items()):
        if name.startswith("test_") and callable(candidate):
            candidate()
    print("Cloud tool contract evolution tests passed")
