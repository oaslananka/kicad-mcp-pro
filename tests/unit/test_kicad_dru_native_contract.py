"""Issue #1770: use actual KiCad 10 .kicad_dru grammar end-to-end."""

from __future__ import annotations

import json

import pytest

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools import routing_rules
from kicad_mcp.tools.validation import _build_constraint_node
from kicad_mcp.utils.dru import dump_dru, find_rule, iter_rule_nodes, parse_dru
from tests.conftest import call_tool_text

_NATIVE = """(version 1)
# A user-maintained custom rule file.
(rule "Existing HV"
  (condition "A.NetClass == 'HV'")
  (constraint clearance (min 1.5mm))
)
(rule "Low voltage"
  (constraint clearance (min 0.2mm))
)
"""


def test_kicad_native_top_level_rules_and_comments_round_trip() -> None:
    root, version = parse_dru(_NATIVE)
    assert version == "1"
    assert [rule[1] for rule in iter_rule_nodes(root)] == ["Existing HV", "Low voltage"]
    serialized = dump_dru(root, version=version)
    assert serialized.startswith("(version 1)\n")
    assert "(rules" not in serialized
    assert [rule[1] for rule in iter_rule_nodes(parse_dru(serialized)[0])] == [
        "Existing HV",
        "Low voltage",
    ]


def test_legacy_rules_wrapper_migrates_to_native_kicad_format() -> None:
    root, version = parse_dru('(rules (rule "old" (constraint clearance (min 0.2mm))))')
    assert version is None
    output = dump_dru(root, version=version)
    assert output.startswith("(version 1)\n")
    assert "(rules" not in output
    assert find_rule(parse_dru(output)[0], "old") is not None


def test_routing_rule_upsert_into_real_kicad_file_keeps_top_level_rules() -> None:
    rule = '(rule "Added" (constraint clearance (min 0.8mm)))'
    updated = routing_rules._upsert_rule(_NATIVE, "Added", rule)
    root, version = parse_dru(updated)
    assert version == "1"
    assert [item[1] for item in iter_rule_nodes(root)] == ["Existing HV", "Low voltage", "Added"]
    replaced = routing_rules._upsert_rule(
        updated, "Added", '(rule "Added" (constraint clearance (min 0.9mm)))'
    )
    assert "(min 0.9mm)" in replaced
    assert "(min 0.8mm)" not in replaced
    assert len(iter_rule_nodes(parse_dru(replaced)[0])) == 3


@pytest.mark.parametrize("number", [5.0, "5.0", ".25"])
def test_rule_numeric_minimums_are_in_millimetres(number: float | str) -> None:
    node = _build_constraint_node("clearance", number, None)
    assert node == ["constraint", "clearance", ["min", f"{number}mm"]]


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ('(version 1 extra) (rule "x")', "Malformed"),
        ('(version 2) (rule "x")', "Unsupported"),
        ("(version 1) ()", "root must contain"),
        ('(rules (not_a_rule "x"))', "invalid rule"),
        ('(rules) (rule "x")', "only root form"),
        ('(version 1) (rule "x") (rules)', "only root form"),
        ('(version 1) (not_a_rule "x")', "root must contain"),
        ('(rule "x")', "requires a leading"),
    ],
)
def test_kicad_native_parser_rejects_malformed_or_unsupported_root(
    content: str, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        parse_dru(content)


def test_kicad_native_parser_accepts_valid_empty_rules_and_comment_parentheses() -> None:
    assert parse_dru("(version 1)") == (["rules"], "1")
    assert parse_dru("# KiCad comment containing unmatched ) and (\n(version 1)") == (
        ["rules"],
        "1",
    )


@pytest.mark.parametrize(
    ("tree", "version", "error"),
    [
        (["not_rules"], None, "internal rules tree"),
        (["rules"], "2", "Unsupported"),
        (["rules", ["not_a_rule", "x"]], None, "Invalid rule node"),
    ],
)
def test_dru_writer_refuses_invalid_data_without_writing(
    tree: list[object], version: str | None, error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        dump_dru(tree, version=version)  # type: ignore[arg-type]


def test_routing_rule_upsert_refuses_mismatched_name() -> None:
    with pytest.raises(ValueError, match="exactly the named custom rule"):
        routing_rules._upsert_rule(
            "(version 1)\n",
            "Expected",
            '(rule "Different" (constraint clearance (min 0.2mm)))',
        )


@pytest.mark.parametrize("value", ["", "   ", float("nan"), float("inf")])
def test_rule_constraint_bounds_reject_empty_or_nonfinite_values(value: float | str) -> None:
    with pytest.raises(ValueError, match="must not be empty|must be finite"):
        _build_constraint_node("clearance", value, None)


def test_rule_constraint_preserves_explicit_units_and_optional_max() -> None:
    assert _build_constraint_node("clearance", None, " 0.5mm ") == [
        "constraint",
        "clearance",
        ["max", "0.5mm"],
    ]


@pytest.mark.anyio
async def test_mcp_drc_create_writes_native_version_and_numeric_units(
    sample_project, monkeypatch
) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    reset_config()
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    result = await call_tool_text(
        server,
        "drc_rule_create",
        {
            "name": "HV",
            "constraint_type": "clearance",
            "min_value": 5.0,
            "condition": "A.NetClass == 'HV'",
        },
    )
    assert "written" in result
    content = (sample_project / "demo.kicad_dru").read_text(encoding="utf-8")
    assert content.startswith("(version 1)\n")
    assert "(rules" not in content
    assert "(min 5.0mm)" in content
    assert find_rule(parse_dru(content)[0], "HV") is not None


@pytest.mark.anyio
async def test_mcp_reads_updates_and_deletes_kicad_native_rules(
    sample_project, monkeypatch
) -> None:
    monkeypatch.setenv("KICAD_MCP_OPERATING_MODE", "write")
    reset_config()
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    dru = sample_project / "demo.kicad_dru"
    dru.write_text(_NATIVE, encoding="utf-8")
    listed = json.loads(await call_tool_text(server, "drc_list_rules", {}))
    assert {"Existing HV", "Low voltage"}.issubset({item["name"] for item in listed["rules"]})
    report = json.loads(await call_tool_text(server, "drc_check_rule_conflicts", {}))
    assert report["conflict_count"] == 0
    await call_tool_text(server, "drc_rule_delete", {"rule_name": "Existing HV"})
    output = dru.read_text(encoding="utf-8")
    assert output.startswith("(version 1)\n")
    assert find_rule(parse_dru(output)[0], "Existing HV") is None
    assert find_rule(parse_dru(output)[0], "Low voltage") is not None
