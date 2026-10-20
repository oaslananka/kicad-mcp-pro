from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.project.design_spec import (
    ProjectDesignIntent,
    ProjectSpecResolution,
    _extract_structured_spec_block,
    _import_spec_extra_fields,
    _import_spec_missing_fields,
    _import_yaml_lines,
    _normalized_unique,
    _parse_import_scalar,
    _parse_simple_yaml,
    _read_design_spec_markdown,
    _render_design_intent,
    _render_project_spec_resolution,
    _sanitize_import_placeholders,
    _select_design_intent_payload,
    _strip_yaml_comment,
    _validation_safe_import_payload,
    _walk_import_values,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("[]", []),
        ("{}", {}),
        ("'Quoted value'", "Quoted value"),
        ('"double quoted"', "double quoted"),
        ("true", True),
        ("YES", True),
        ("off", False),
        ("null", None),
        ("~", None),
        ('["A", 2, true]', ["A", 2, True]),
        ("[A, 2, true]", ["A", 2, True]),
        ('{"name": "U1"}', {"name": "U1"}),
        ("{not-json}", "{not-json}"),
        ("3.25", 3.25),
        ("2e3", 2000.0),
        ("42", 42),
        ("plain-text", "plain-text"),
    ],
)
def test_parse_import_scalar_variants(raw: str, expected: object) -> None:
    assert _parse_import_scalar(raw) == expected


def test_empty_design_spec_rendering_preserves_none_display_contract() -> None:
    rendered = _render_design_intent(ProjectDesignIntent())
    resolution = _render_project_spec_resolution(ProjectSpecResolution())

    assert "- Connector refs: (none)" in rendered
    assert "- Manufacturer: (none)" in rendered
    assert "- Thermal hotspots: (none)" in rendered
    assert "- Explicit source: (none)" in resolution
    assert "- Explicit path: (none)" in resolution


def test_strip_yaml_comment_respects_quoted_hashes_and_escapes() -> None:
    assert _strip_yaml_comment("key: value # comment") == "key: value"
    assert _strip_yaml_comment("key: 'a # b' # comment") == "key: 'a # b'"
    assert _strip_yaml_comment('key: "a \\"# b" # comment') == 'key: "a \\"# b"'


def test_import_yaml_lines_ignores_comments_and_tracks_indent() -> None:
    assert _import_yaml_lines(
        """
# ignored
root:
  child: 3 # trailing
  quoted: "a # b"
"""
    ) == [
        (0, "root:"),
        (2, "child: 3"),
        (2, 'quoted: "a # b"'),
    ]


def test_parse_simple_yaml_nested_dicts_lists_and_continuations() -> None:
    parsed = _parse_simple_yaml(
        """
project:
  enabled: true
  empty:
  refs:
    - J1
    - J2
  rails:
    - name: +3V3
      voltage_v: 3.3
      current_max_a: 1
    - metadata:
        source: regulator
      name: +5V
"""
    )

    assert parsed == {
        "project": {
            "enabled": True,
            "empty": None,
            "refs": ["J1", "J2"],
            "rails": [
                {"name": "+3V3", "voltage_v": 3.3, "current_max_a": 1},
                {"metadata": {"source": "regulator"}, "name": "+5V"},
            ],
        }
    }


def test_parse_simple_yaml_empty_and_unsupported_layout() -> None:
    assert _parse_simple_yaml("# comment only") == {}

    with pytest.raises(ValueError, match="Unsupported YAML layout"):
        _parse_simple_yaml("key: value\n- stray")


def test_extract_structured_spec_block_supports_all_documented_shapes() -> None:
    payload, source = _extract_structured_spec_block(
        '{"design_intent": {"required_sheets": ["Main"]}}'
    )
    assert source == "json"
    assert payload["design_intent"]["required_sheets"] == ["Main"]

    payload, source = _extract_structured_spec_block(
        """---
design_intent:
  required_sheets: [Main]
---
prose
"""
    )
    assert source == "frontmatter"
    assert payload["design_intent"]["required_sheets"] == ["Main"]

    payload, source = _extract_structured_spec_block(
        """```json
{"design_intent": {"required_sheets": ["Power"]}}
```"""
    )
    assert source == "fenced"
    assert payload["design_intent"]["required_sheets"] == ["Power"]

    payload, source = _extract_structured_spec_block(
        """```yaml
design_intent:
  required_sheets:
    - IO
```"""
    )
    assert source == "fenced"
    assert payload["design_intent"]["required_sheets"] == ["IO"]


def test_extract_structured_spec_block_rejects_empty_and_unstructured_text() -> None:
    with pytest.raises(ValueError, match="No design-spec content"):
        _extract_structured_spec_block("   ")

    with pytest.raises(ValueError, match="No structured design spec found"):
        _extract_structured_spec_block("plain prose only")


def test_normalized_unique_strips_empties_and_casefold_duplicates() -> None:
    assert _normalized_unique([" J1 ", "", "j1", "J2", " J2 "]) == ["J1", "J2"]


def test_select_design_intent_payload_handles_wrapped_and_direct_specs() -> None:
    wrapped = {
        "project_spec": {"required_sheets": ["Main"]},
        "notes": "retained",
        "populate": ["U1"],
    }
    intent, extras = _select_design_intent_payload(wrapped)
    assert intent == {"required_sheets": ["Main"]}
    assert extras == {"notes": "retained", "populate": ["U1"]}

    direct = {"required_sheets": ["Main"]}
    assert _select_design_intent_payload(direct) == (direct, {})


def test_walk_and_sanitize_import_placeholders_recurses() -> None:
    payload = {
        "required_sheets": ["Main", "{...}"],
        "mechanical": {"board_width_mm": "TBD", "board_height_mm": 50},
        "nested": [{"value": "ok"}, "<unknown>"],
    }

    assert _walk_import_values(payload) == [
        "required_sheets[1]",
        "mechanical.board_width_mm",
        "nested[1]",
    ]
    assert _sanitize_import_placeholders(payload) == {
        "required_sheets": ["Main"],
        "mechanical": {"board_height_mm": 50},
        "nested": [{"value": "ok"}],
    }


def test_validation_safe_import_payload_filters_incomplete_models() -> None:
    safe = _validation_safe_import_payload(
        {
            "required_sheets": ["Main"],
            "power_rails": [
                {"name": "+3V3", "voltage_v": 3.3, "current_max_a": 1.0},
                {"name": "+5V", "voltage_v": 5.0},
                "not-a-mapping",
            ],
            "interfaces": [
                {"kind": "usb2", "refs": ["J1"]},
                {"refs": ["J2"]},
                "not-a-mapping",
            ],
        }
    )

    assert safe["power_rails"] == [{"name": "+3V3", "voltage_v": 3.3, "current_max_a": 1.0}]
    assert safe["interfaces"] == [{"kind": "usb2", "refs": ["J1"]}]


def test_import_spec_missing_fields_reports_nested_requirements() -> None:
    missing = _import_spec_missing_fields(
        {
            "required_sheets": [],
            "mechanical": {"board_width_mm": "{...}", "board_height_mm": None},
            "power_rails": [
                "bad-entry",
                {"name": "", "voltage_v": 3.3, "current_max_a": "TBD"},
            ],
        }
    )

    assert missing == [
        "required_sheets",
        "mechanical.board_width_mm",
        "mechanical.board_height_mm",
        "power_rails[0]",
        "power_rails[1].name",
        "power_rails[1].current_max_a",
    ]


def test_import_spec_extra_fields_separates_supported_extras_and_unknowns() -> None:
    extras = _import_spec_extra_fields(
        {
            "required_sheets": ["Main"],
            "notes": "operator note",
            "dnp": ["R9"],
            "mystery_field": 42,
        },
        {"populate": ["U1"]},
    )

    assert extras == {
        "populate": ["U1"],
        "notes": "operator note",
        "dnp": ["R9"],
        "unsupported_fields": ["mystery_field"],
    }


def test_read_design_spec_markdown_prefers_inline_and_requires_one_source() -> None:
    assert _read_design_spec_markdown(None, "  inline spec  ") == (
        "  inline spec  ",
        "inline",
    )
    with pytest.raises(ValueError, match="Provide either markdown or path"):
        _read_design_spec_markdown(None, None)


def test_parse_simple_yaml_skips_unexpected_deeper_mapping_rows() -> None:
    assert _parse_simple_yaml(
        """
root:
  child: 1
    stray
"""
    ) == {"root": {"child": 1}}


def test_infer_design_intent_from_board_with_footprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.config import get_config
    from kicad_mcp.project.design_spec import _infer_design_intent_from_board

    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb)\n", encoding="utf-8")
    monkeypatch.setattr(get_config(), "pcb_file", pcb_file)
    monkeypatch.setattr(
        "kicad_mcp.tools.board_file._parse_board_footprint_blocks",
        lambda _content: {
            "U1": {"x_mm": 10.0, "y_mm": 10.0},
            "C1": {"x_mm": 12.0, "y_mm": 10.0},
        },
    )
    _intent, notes = _infer_design_intent_from_board()
    assert any("decoupling pair" in note for note in notes)


def test_parse_simple_yaml_empty_dict_item() -> None:
    yaml_text = """items:
  - key:
"""
    parsed = _parse_simple_yaml(yaml_text)
    assert parsed == {"items": [{"key": None}]}


def test_parse_simple_yaml_empty_list_item_and_nested_block() -> None:
    from kicad_mcp.project.design_spec import _SimpleYamlParser

    parser = _SimpleYamlParser([(0, "- "), (2, "nested: 42"), (0, "- ")])
    parsed = parser.parse()
    assert parsed == [{"nested": 42}, None]


def test_import_helpers_preserve_empty_fallback_and_missing_mechanical_contract() -> None:
    from kicad_mcp.project.design_spec import _extract_yaml_frontmatter

    # An invalid JSON list still uses the conservative YAML-like fallback.
    assert _parse_import_scalar("[ ]") == []
    assert _parse_import_scalar("[\u00a0]") == []  # Non-JSON whitespace fallback.
    # A valid YAML list is not a supported mapping-shaped frontmatter block.
    assert _extract_yaml_frontmatter("---\n- item\n---\n") is None
    assert _import_spec_missing_fields({"required_sheets": ["Main"], "mechanical": None}) == [
        "mechanical.board_width_mm",
        "mechanical.board_height_mm",
    ]


def test_design_spec_rendering_preserves_optional_compliance_and_cost() -> None:
    from kicad_mcp.models.intent import ComplianceTarget, CostTarget

    rendered = _render_design_intent(
        ProjectDesignIntent(
            compliance=[ComplianceTarget(kind="ce_emc")],
            cost=CostTarget(unit_cost_usd_max=12.5),
        )
    )
    assert "- Compliance: ce_emc" in rendered
    assert "- Cost target: <$12.50/unit" in rendered
    assert rendered.index("- Compliance:") < rendered.index("- Cost target:")


def test_validate_design_intent_checks_references_on_existing_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.config import get_config
    from kicad_mcp.project.design_spec import validate_design_intent

    board = tmp_path / "board.kicad_pcb"
    board.write_text("(kicad_pcb)\n", encoding="utf-8")
    monkeypatch.setattr(get_config(), "pcb_file", board)
    monkeypatch.setattr(
        "kicad_mcp.tools.board_file._parse_board_footprint_blocks",
        lambda _content: {"U1": {"x_mm": 1.0, "y_mm": 2.0}},
    )
    assert validate_design_intent(ProjectDesignIntent(connector_refs=["J1", "U1"])) == [
        "Connector ref 'J1' is not present on the PCB."
    ]


def test_design_spec_rendering_preserves_rail_and_interface_order() -> None:
    from kicad_mcp.models.intent import InterfaceSpec, PowerRailSpec

    intent = ProjectDesignIntent(
        power_rails=[PowerRailSpec(name="+3V3", voltage_v=3.3, current_max_a=1.0, source_ref="U1")],
        interfaces=[
            InterfaceSpec(kind="usb2", impedance_target_ohm=90.0, differential=True),
            InterfaceSpec(kind="i2c"),
        ],
    )
    rendered = _render_design_intent(intent)
    assert "- Power rails: 1\n  +3V3: 3.3V / 1.0A via U1" in rendered
    assert "- Interfaces: 2\n  usb2  90.0ohm diff\n  i2c" in rendered
    assert rendered.index("- Power rails:") < rendered.index("- Interfaces:")
