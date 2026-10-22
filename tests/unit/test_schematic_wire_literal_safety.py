"""Issue #1371: quoted S-expression text must never become electrical copper."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_mcp.errors import SchematicWriteUnsafeError
from kicad_mcp.tools import schematic as s

PHANTOM = "(wire (pts (xy 50 50) (xy 60 50)))"
REAL = '(wire (pts (xy 0 0) (xy 10 0)) (uuid "11111111-1111-4111-8111-111111111111"))'


def schematic(*nodes: str) -> str:
    return (
        '(kicad_sch (version 20260306) (generator "eeschema")'
        ' (uuid "55555555-5555-4555-8555-555555555555")'
        ' (paper "A4") (lib_symbols)\n'
        + "\n".join(nodes)
        + '\n(sheet_instances (path "/" (page "1")))\n)\n'
    )


def quoted_text(value: str) -> str:
    return (
        f'(text "{value}" (at 25 20 0) (effects (font (size 1.27 1.27))) '
        '(uuid "22222222-2222-4222-8222-222222222222"))'
    )


def test_embedded_wire_literal_remains_unchanged_through_normalization() -> None:
    source = schematic(REAL, quoted_text(PHANTOM))
    output = s._normalize_schematic_wire_connectivity(source)
    assert PHANTOM in output
    assert quoted_text(PHANTOM) in output
    assert s._wire_segments_from_content(output) == [(0.0, 0.0, 10.0, 0.0)]
    assert PHANTOM in s._remove_wire_blocks(output)


@pytest.mark.parametrize(
    "value",
    [
        PHANTOM,
        r"prefix \"escaped quote\" " + PHANTOM + " suffix",
        r"two literals " + PHANTOM + " and " + PHANTOM,
    ],
)
def test_writer_preserves_quoted_wire_text_in_existing_file(tmp_path: Path, value: str) -> None:
    path = tmp_path / "literal.kicad_sch"
    old = schematic(REAL, quoted_text(value))
    path.write_text(old)
    label = '(label "ADDED" (at 0 0 0) (uuid "33333333-3333-4333-8333-333333333333"))'

    with patch.object(s, "_record_schematic_visual_diff", return_value=None):
        s._transactional_write_to_schematic_file(
            path,
            lambda content: content.replace(
                "\n(sheet_instances", "\n" + label + "\n(sheet_instances"
            ),
        )

    after = path.read_text()
    assert quoted_text(value) in after
    assert len(s._extract_wires(after)) == 1
    assert '(label "ADDED"' in after


def test_normalizer_preserves_quoted_symbol_property_string() -> None:
    node = (
        '(symbol (lib_id "Device:R") (at 25 25 0) '
        f'(property "Value" "{PHANTOM}")'
        '(uuid "44444444-4444-4444-8444-444444444444"))'
    )
    updated = s._normalize_schematic_wire_connectivity(schematic(REAL, node))
    assert f'(property "Value" "{PHANTOM}")' in updated
    assert len(s._extract_wires(updated)) == 1


def test_writer_guard_checks_mutation_before_wire_normalization(tmp_path: Path) -> None:
    path = tmp_path / "explicit-loss.kicad_sch"
    source = schematic(REAL, quoted_text(PHANTOM))
    path.write_text(source)
    with pytest.raises(SchematicWriteUnsafeError):
        s._transactional_write_to_schematic_file(
            path,
            lambda content: content.replace(REAL, ""),
        )
    assert path.read_text() == source


def test_normalization_refuses_non_wire_mutation_even_when_node_loss_allowed() -> None:
    source = schematic(REAL, quoted_text(PHANTOM))
    with (
        patch.object(s, "_remove_wire_blocks", return_value=schematic()),
        pytest.raises(SchematicWriteUnsafeError, match="normalization"),
    ):
        s._normalize_schematic_wire_connectivity(source)


def test_exact_duplicate_real_wires_normalize_without_changing_coverage() -> None:
    duplicate = '(wire (pts (xy 10 0) (xy 0 0)) (uuid "66666666-6666-4666-8666-666666666666"))'
    result = s._normalize_schematic_wire_connectivity(schematic(REAL, duplicate))
    assert len(s._extract_wires(result)) == 1
    assert s._wire_segments_from_content(result) == [(0.0, 0.0, 10.0, 0.0)]


def test_normalizer_preserves_degenerate_wire_with_nonzero_wire() -> None:
    zero = '(wire (pts (xy 22 22) (xy 22 22)) (uuid "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"))'
    source = schematic(REAL, zero, quoted_text(PHANTOM))
    result = s._normalize_schematic_wire_connectivity(source)
    assert zero in result
    assert quoted_text(PHANTOM) in result
    assert len(s._extract_wires(result)) == 2


def test_nearly_degenerate_both_axes_is_preserved_while_deduplicating() -> None:
    tol = s.SNAP_TOLERANCE_MM
    almost = (
        f"(wire (pts (xy 22 22) (xy {22 + tol * 0.8:.9f} "
        f'{22 + tol * 0.8:.9f})) (uuid "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"))'
    )
    source = schematic(REAL, almost)
    result = s._normalize_schematic_wire_connectivity(source)
    assert almost in result


def test_large_root_wire_batch_no_unbounded_repeated_insert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_append = s._append_before_sheet_instances
    insertions: list[str] = []

    def counted(content: str, block: str) -> str:
        insertions.append(block)
        return real_append(content, block)

    monkeypatch.setattr(s, "_append_before_sheet_instances", counted)
    source = schematic(*(f"(wire (pts (xy {i} 0) (xy {i} 1)))" for i in range(150)))
    output = s._normalize_schematic_wire_connectivity(source)
    assert len(s._extract_wires(output)) == 150
    assert len(insertions) == 1
