"""Stackup changes preserve explicit footprint rule-area intent (#1947)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kicad_mcp.models.pcb import StackupLayerSpec
from kicad_mcp.tools import pcb
from kicad_mcp.utils.sexpr import iter_root_children

ALL_ID = "11111111-1111-4111-8111-111111111111"
FIXED_ID = "22222222-2222-4222-8222-222222222222"
FIELD = "KICAD_MCP_RULE_LAYER_INTENT"
ALL_LAYERS = ["F.Cu", "B.Cu", *(f"In{i}.Cu" for i in range(1, 31))]


def _layer_clause(layers: list[str]) -> str:
    return "(layers " + " ".join(f'"{layer}"' for layer in layers) + ")"


def _rule(uid: str, layers: list[str], name: str) -> str:
    return (
        f'(zone {_layer_clause(layers)} (uuid "{uid}") (name "{name}") '
        "(keepout (tracks not_allowed) (copperpour not_allowed)) "
        "(polygon (pts (xy 0 0) (xy 5 0) (xy 5 5) (xy 0 5))))"
    )


def _stackup(count: int) -> list[StackupLayerSpec]:
    layers = []
    for index, name in enumerate(["F.Cu", *(f"In{i}.Cu" for i in range(1, count - 1)), "B.Cu"]):
        if index:
            layers.append(
                StackupLayerSpec(
                    name=f"dielectric_{index}", type="core", thickness_mm=0.2, material="FR4"
                )
            )
        layers.append(
            StackupLayerSpec(name=name, type="signal", thickness_mm=0.035, material="Copper")
        )
    return layers


def _board(footprint: str = "") -> str:
    return (
        '(kicad_pcb (version 20260206) (generator "pcbnew") (general (thickness 1.6))\n'
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (7 "F.Fab" user))\n' + footprint + "\n)\n"
    )


def _rules(content: str) -> dict[str, str]:
    footprint = next(value for key, value in iter_root_children(content) if key == "footprint")
    return {
        next(value for key, value in iter_root_children(rule) if key == "uuid").split('"')[1]: rule
        for key, rule in iter_root_children(footprint)
        if key == "zone"
    }


def _layers(rule: str) -> set[str]:
    clause = next(value for key, value in iter_root_children(rule) if key == "layers")
    return set(re.findall(r'"([^"]+)"', clause))


@pytest.mark.parametrize("declared", [ALL_LAYERS, ["*.Cu"]])
def test_imported_all_copper_intent_survives_stackup_transitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, declared: list[str]
) -> None:
    library = tmp_path / "RF.kicad_mod"
    fixed = _rule(FIXED_ID, ["F.Cu", "B.Cu"], "deliberately outer only")
    library.write_text(
        '(footprint "RF" (layer "F.Cu") (property "Reference" "REF**" (at 0 0)) '
        '(property "Value" "RF" (at 0 0)) ' + _rule(ALL_ID, declared, "antenna") + fixed + ")",
        encoding="utf-8",
    )
    original = library.read_bytes()
    monkeypatch.setattr(pcb, "_footprint_file", lambda *_: library)
    rendered = pcb._render_board_footprint_block(
        "RF:RF", reference="U1", value="RF", x_mm=20, y_mm=20, rotation=0, pad_nets={}
    )
    assert f'(property "{FIELD}" ' in rendered
    # Simulate KiCad's proven two-layer native normalization, which drops future layers.
    normalized = rendered.replace(_layer_clause(declared), _layer_clause(["F.Cu", "B.Cu"]), 1)
    content = _board(normalized)
    fixed_before = _rules(content)[FIXED_ID]
    for count in (4, 2, 4, 6):
        content = pcb._apply_stackup_to_board(content, _stackup(count))
        rules = _rules(content)
        assert _layers(rules[ALL_ID]) == {
            "F.Cu",
            "B.Cu",
            *(f"In{i}.Cu" for i in range(1, count - 1)),
        }
        assert rules[FIXED_ID] == fixed_before
    assert library.read_bytes() == original


def test_ambiguous_saved_footprint_is_not_silently_widened() -> None:
    footprint = (
        '(footprint "RF:RF" (layer "F.Cu") (uuid "33333333-3333-4333-8333-333333333333") '
        '(at 20 20) (property "Reference" "U1" (at 0 0)) '
        + _rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna")
        + ")"
    )
    with pytest.raises(ValueError, match=r"(?i)ambiguous.*U1"):
        pcb._apply_stackup_to_board(_board(footprint), _stackup(4))


def test_unrelated_board_rule_is_not_reinterpreted() -> None:
    root_rule = _rule(ALL_ID, ["F.Cu", "B.Cu"], "custom board area")
    content = pcb._apply_stackup_to_board(_board(root_rule), _stackup(4))
    assert root_rule in content


@pytest.mark.parametrize("decision", ["all_copper", "fixed_layers"])
def test_existing_ambiguous_rule_requires_explicit_identity_scoped_resolution(
    decision: str,
) -> None:
    root_id = "33333333-3333-4333-8333-333333333333"
    footprint = (
        f'(footprint "RF:RF" (layer "F.Cu") (uuid "{root_id}") '
        '(at 20 20) (property "Reference" "U1" (at 0 0)) '
        + _rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna")
        + ")"
    )
    key = f"{root_id}/{ALL_ID}"
    with pytest.raises(ValueError, match=key):
        pcb._apply_stackup_to_board(_board(footprint), _stackup(4))
    updated = pcb._apply_stackup_to_board(
        _board(footprint), _stackup(4), keepout_layer_intents={key: decision}
    )
    expected = {"F.Cu", "B.Cu"}
    if decision == "all_copper":
        expected.update({"In1.Cu", "In2.Cu"})
    assert _layers(_rules(updated)[ALL_ID]) == expected
    grown = pcb._apply_stackup_to_board(updated, _stackup(6))
    if decision == "all_copper":
        expected.update({"In3.Cu", "In4.Cu"})
    assert _layers(_rules(grown)[ALL_ID]) == expected
    with pytest.raises(ValueError, match="Unknown.*rule"):
        pcb._apply_stackup_to_board(
            _board(footprint),
            _stackup(4),
            keepout_layer_intents={key: decision, f"{root_id}/{FIXED_ID}": "fixed_layers"},
        )


def test_cloned_footprint_retains_intent_for_its_new_rule_uuid() -> None:
    from kicad_mcp.pcb.rule_layer_intent import mark_library_keepout_intent

    source = mark_library_keepout_intent(
        '(footprint "RF:RF" (layer "F.Cu") '
        '(uuid "33333333-3333-4333-8333-333333333333") '
        '(property "Reference" "U1" (at 0 0)) ' + _rule(ALL_ID, ALL_LAYERS, "antenna") + ")"
    )
    normalized = source.replace(_layer_clause(ALL_LAYERS), _layer_clause(["F.Cu", "B.Cu"]), 1)
    cloned = pcb._refresh_uuid_fields(normalized)
    assert ALL_ID not in cloned
    grown = pcb._apply_stackup_to_board(_board(cloned), _stackup(4))
    rules = _rules(grown)
    assert len(rules) == 1
    assert _layers(next(iter(rules.values()))) == {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}


ROOT_ID = "33333333-3333-4333-8333-333333333333"


def _footprint(*children: str, root_id: str = ROOT_ID) -> str:
    return (
        f'(footprint "RF:RF" (layer "F.Cu") (uuid "{root_id}") '
        '(at 20 20) (property "Reference" "U1" (at 0 0)) ' + " ".join(children) + ")"
    )


@pytest.mark.parametrize(
    "value", ["v2:unknown", "v1:not-a-uuid=all_copper", f"v1:{ALL_ID}=unknown"]
)
def test_invalid_saved_provenance_refuses_layer_change(value: str) -> None:
    footprint = _footprint(
        _rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna"), f'(property "{FIELD}" "{value}")'
    )
    with pytest.raises(ValueError, match=f"Invalid {FIELD}"):
        pcb._apply_stackup_to_board(_board(footprint), _stackup(4))


def test_deleted_rule_and_conflicting_mask_require_reconciliation() -> None:
    from kicad_mcp.pcb.rule_layer_intent import mark_library_keepout_intent

    original = _rule(ALL_ID, ALL_LAYERS, "antenna")
    marked = mark_library_keepout_intent(_footprint(original))
    with pytest.raises(ValueError, match="Stale.*provenance"):
        pcb._apply_stackup_to_board(_board(marked.replace(original, "")), _stackup(4))
    narrowed = marked.replace(_layer_clause(ALL_LAYERS), _layer_clause(["F.Cu"]), 1)
    with pytest.raises(ValueError, match="Ambiguous.*U1"):
        pcb._apply_stackup_to_board(_board(narrowed), _stackup(4))
    corrected = pcb._apply_stackup_to_board(
        _board(narrowed), _stackup(4), keepout_layer_intents={f"{ROOT_ID}/{ALL_ID}": "fixed_layers"}
    )
    assert _layers(_rules(corrected)[ALL_ID]) == {"F.Cu"}


def test_source_marker_is_reserved_and_missing_rule_uuid_is_assigned() -> None:
    from kicad_mcp.pcb.rule_layer_intent import mark_library_keepout_intent

    marked = mark_library_keepout_intent(_footprint(_rule(ALL_ID, ALL_LAYERS, "antenna")))
    with pytest.raises(ValueError, match="reserved"):
        mark_library_keepout_intent(marked)
    no_uuid = _rule(ALL_ID, ALL_LAYERS, "antenna").replace(f'(uuid "{ALL_ID}")', "")
    marked = mark_library_keepout_intent(_footprint(no_uuid))
    identity = next(iter(_rules(_board(marked))))
    assert identity != ALL_ID and f"{identity}=all_copper" in marked


@pytest.mark.parametrize(
    "rule",
    [
        _rule("broken", ALL_LAYERS, "antenna"),
        _rule(ALL_ID, ALL_LAYERS, "a") + _rule(ALL_ID, ALL_LAYERS, "b"),
    ],
)
def test_invalid_or_duplicate_rule_uuid_refuses_library_import(rule: str) -> None:
    from kicad_mcp.pcb.rule_layer_intent import mark_library_keepout_intent

    with pytest.raises(ValueError, match="keepout UUID"):
        mark_library_keepout_intent(_footprint(rule))


def test_ordinary_and_non_copper_zones_are_not_marked() -> None:
    from kicad_mcp.pcb.rule_layer_intent import mark_library_keepout_intent

    footprint = _footprint(
        '(zone (layer "F.Cu") (polygon (pts (xy 0 0) (xy 1 1))))',
        "(zone (keepout (tracks not_allowed)))",
        '(zone (layer "F.Mask") (keepout (tracks not_allowed)))',
    )
    assert mark_library_keepout_intent(footprint) == footprint
    assert footprint in pcb._apply_stackup_to_board(_board(footprint), _stackup(4))
    assert FIELD not in pcb._refresh_uuid_fields(footprint)


def test_explicit_full_declaration_on_existing_board_can_be_preserved() -> None:
    content = pcb._apply_stackup_to_board(
        _board(_footprint(_rule(ALL_ID, ALL_LAYERS, "antenna"))), _stackup(4)
    )
    assert _layers(_rules(content)[ALL_ID]) == {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}
    assert f"{ALL_ID}=all_copper" in content


def test_missing_identity_and_wildcard_fixed_choice_are_refused() -> None:
    no_uuid = _rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna").replace(f'(uuid "{ALL_ID}")', "")
    with pytest.raises(ValueError, match="Save the board in KiCad"):
        pcb._apply_stackup_to_board(_board(_footprint(no_uuid)), _stackup(4))
    with pytest.raises(ValueError, match="concrete rule layer mask"):
        pcb._apply_stackup_to_board(
            _board(_footprint(_rule(ALL_ID, ["*.Cu"], "antenna"))),
            _stackup(4),
            keepout_layer_intents={f"{ROOT_ID}/{ALL_ID}": "fixed_layers"},
        )
    with pytest.raises(ValueError, match="without a board layer table"):
        pcb._apply_stackup_to_board(
            "(kicad_pcb)", _stackup(4), keepout_layer_intents={f"{ROOT_ID}/{ALL_ID}": "all_copper"}
        )


def test_duplicate_composite_decision_is_refused_and_stale_clone_does_not_guess() -> None:
    from kicad_mcp.pcb.rule_layer_intent import (
        mark_library_keepout_intent,
        remap_cloned_rule_intents,
    )

    footprint = _footprint(_rule(ALL_ID, ["F.Cu", "B.Cu"], "antenna"))
    with pytest.raises(ValueError, match="Duplicate footprint/rule identity"):
        pcb._apply_stackup_to_board(
            _board(footprint + footprint),
            _stackup(4),
            keepout_layer_intents={f"{ROOT_ID}/{ALL_ID}": "all_copper"},
        )
    with pytest.raises(ValueError, match="Cannot safely remap"):
        remap_cloned_rule_intents(mark_library_keepout_intent(footprint), {})
