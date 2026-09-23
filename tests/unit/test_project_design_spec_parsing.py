from __future__ import annotations

import pytest

from kicad_mcp.project.design_spec import (
    _extract_structured_spec_block,
    _import_spec_extra_fields,
    _import_spec_missing_fields,
    _import_yaml_lines,
    _normalized_unique,
    _parse_import_scalar,
    _parse_simple_yaml,
    _read_design_spec_markdown,
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
