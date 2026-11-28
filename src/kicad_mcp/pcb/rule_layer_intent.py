"""Preserve explicit footprint copper rule-area intent across native stackups.

KiCad normalizes a rule area to enabled layers on save. Only explicit library
declarations or a previously recorded intent may justify restoring future
copper coverage. A current full-stack mask alone is not provenance.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from ..models.pcb import KeepoutLayerIntent, KeepoutLayerIntents
from ..utils.sexpr import _sexpr_string, _unescape_sexpr_string, iter_root_child_spans

FIELD = "KICAD_MCP_RULE_LAYER_INTENT"
COPPER_LAYERS = frozenset({"F.Cu", "B.Cu", *(f"In{i}.Cu" for i in range(1, 31))})
_PROPERTY = re.compile(r'\(property\s+"((?:\\.|[^"\\])*)"\s+"((?:\\.|[^"\\])*)"')
_UUID = re.compile(r'\(uuid\s+"([^"]+)"\s*\)')
_LAYER_NAME = re.compile(r'"([^"]+)"')


@dataclass(frozen=True)
class _RuleArea:
    start: int
    end: int
    layer_start: int
    layer_end: int
    identity: str | None
    layers: frozenset[str]


def _canonical_uuid(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.int != 0 and str(parsed) == value


def _explicit_all(layers: frozenset[str]) -> bool:
    return layers in (COPPER_LAYERS, frozenset({"*.Cu"}))


def _potential_full_stack(layers: frozenset[str]) -> bool:
    """A mask that could have been normalized on any smaller stackup."""
    inner_count = len(layers) - 2
    return layers == {"F.Cu", "B.Cu", *(f"In{i}.Cu" for i in range(1, inner_count + 1))}


def _properties(footprint: str) -> list[tuple[str, str, int, int]]:
    fields: list[tuple[str, str, int, int]] = []
    for name, start, end in iter_root_child_spans(footprint):
        if name != "property":
            continue
        match = _PROPERTY.match(footprint[start:end])
        if match:
            fields.append(
                (
                    _unescape_sexpr_string(match[1]),
                    _unescape_sexpr_string(match[2]),
                    start + match.start(2),
                    start + match.end(2),
                )
            )
    return fields


def _reference(footprint: str) -> str:
    return next(
        (value for name, value, _, _ in _properties(footprint) if name == "Reference"),
        "(unknown footprint)",
    )


def _read_intents(footprint: str) -> tuple[KeepoutLayerIntents, tuple[int, int] | None]:
    entries = [
        (value, start, end) for name, value, start, end in _properties(footprint) if name == FIELD
    ]
    if not entries:
        return {}, None
    if len(entries) != 1 or not entries[0][0].startswith("v1:"):
        raise ValueError(f"Invalid {FIELD} provenance on {_reference(footprint)}.")
    value, start, end = entries[0]
    intents: KeepoutLayerIntents = {}
    for item in value[3:].split(","):
        identity, sep, intent = item.partition("=")
        if not sep or not _canonical_uuid(identity) or identity in intents:
            raise ValueError(f"Invalid {FIELD} rule identity on {_reference(footprint)}.")
        if intent == "all_copper":
            intents[identity] = "all_copper"
        elif intent == "fixed_layers":
            intents[identity] = "fixed_layers"
        else:
            raise ValueError(f"Invalid {FIELD} layer intent on {_reference(footprint)}.")
    return intents, (start, end)


def _write_intents(
    footprint: str, intents: KeepoutLayerIntents, span: tuple[int, int] | None
) -> str:
    if not intents:
        return footprint
    value = "v1:" + ",".join(f"{identity}={intent}" for identity, intent in sorted(intents.items()))
    if span is not None:
        start, end = span
        if footprint[start:end] == value:
            return footprint
        return footprint[:start] + value + footprint[end:]
    return (
        footprint[:-1] + f'\n\t(property "{FIELD}" {_sexpr_string(value)} '
        '(at 0 0 0) (layer "F.Fab") (hide yes) (effects (font (size 1 1))))\n)'
    )


def _rule_area(footprint: str, start: int, end: int) -> _RuleArea | None:
    zone = footprint[start:end]
    children = list(iter_root_child_spans(zone))
    if not any(name == "keepout" for name, _, _ in children):
        return None
    layer_spans = [(a, b) for name, a, b in children if name in {"layer", "layers"}]
    if len(layer_spans) != 1:
        return None
    a, b = layer_spans[0]
    layers = frozenset(_LAYER_NAME.findall(zone[a:b]))
    if not layers or not (layers <= COPPER_LAYERS or layers == {"*.Cu"}):
        return None
    identities = [zone[a:b] for name, a, b in children if name == "uuid"]
    identity = None
    if identities:
        match = _UUID.fullmatch(identities[0])
        if len(identities) != 1 or match is None or not _canonical_uuid(match[1]):
            raise ValueError(f"Invalid copper keepout UUID on {_reference(footprint)}.")
        identity = match[1]
    return _RuleArea(start, end, start + a, start + b, identity, layers)


def _areas(footprint: str) -> list[_RuleArea]:
    rules = []
    identities: set[str] = set()
    for name, start, end in iter_root_child_spans(footprint):
        if name != "zone":
            continue
        rule = _rule_area(footprint, start, end)
        if rule is None:
            continue
        if rule.identity is not None:
            if rule.identity in identities:
                raise ValueError(f"Duplicate copper keepout UUID on {_reference(footprint)}.")
            identities.add(rule.identity)
        rules.append(rule)
    return rules


def _apply_edits(content: str, edits: list[tuple[int, int, str]]) -> str:
    for start, end, value in reversed(sorted(edits)):
        content = content[:start] + value + content[end:]
    return content


def mark_library_keepout_intent(footprint: str) -> str:
    """Capture source masks before KiCad can truncate them to the current board."""
    existing, span = _read_intents(footprint)
    if existing or span is not None:
        raise ValueError(f"{FIELD} is reserved for board rule-area provenance.")
    intents: KeepoutLayerIntents = {}
    edits: list[tuple[int, int, str]] = []
    for rule in _areas(footprint):
        identity = rule.identity
        if identity is None:
            identity = str(uuid.uuid4())
            edits.append((rule.end - 1, rule.end - 1, f' (uuid "{identity}")'))
        intents[identity] = "all_copper" if _explicit_all(rule.layers) else "fixed_layers"
    return _write_intents(_apply_edits(footprint, edits), intents, None)


def _decision_key(footprint: str, rule: _RuleArea) -> str | None:
    for name, start, end in iter_root_child_spans(footprint):
        if name == "uuid":
            match = _UUID.fullmatch(footprint[start:end])
            if match and _canonical_uuid(match[1]) and rule.identity is not None:
                return f"{match[1]}/{rule.identity}"
    return None


def _ambiguous(footprint: str, rule: _RuleArea) -> ValueError:
    key = _decision_key(footprint, rule)
    action = (
        f"Review the intended coverage, then supply keepout_layer_intents "
        f'{{"{key}": "all_copper"}} or "fixed_layers" for that key.'
        if key
        else "Save the board in KiCad to establish rule and footprint UUIDs; review its intent."
    )
    return ValueError(
        f"Ambiguous copper keepout intent on {_reference(footprint)} "
        f"(rule {rule.identity or 'missing UUID'}). "
        "The saved layer mask cannot establish all-copper versus fixed intent. "
        f"{action} No board change applied."
    )


def _resolve_rule_intent(
    footprint: str,
    rule: _RuleArea,
    intents: KeepoutLayerIntents,
    decisions: KeepoutLayerIntents,
    used: set[str],
    old_copper: set[str],
) -> KeepoutLayerIntent | None:
    key = _decision_key(footprint, rule) if decisions else None
    if rule.identity is not None and key is not None and key in decisions:
        if key in used:
            raise ValueError(f"Duplicate footprint/rule identity {key}.")
        used.add(key)
        choice = decisions[key]
        if choice == "fixed_layers" and rule.layers == {"*.Cu"}:
            raise ValueError("Fixed layers require a concrete rule layer mask.")
        intents[rule.identity] = choice
        return choice

    intent = intents.get(rule.identity) if rule.identity is not None else None
    if intent is None:
        if _explicit_all(rule.layers) and rule.identity is not None:
            intent = "all_copper"
            intents[rule.identity] = intent
        elif _potential_full_stack(rule.layers) or _explicit_all(rule.layers):
            raise _ambiguous(footprint, rule)
    if intent == "all_copper" and rule.layers != old_copper and not _explicit_all(rule.layers):
        raise _ambiguous(footprint, rule)
    return intent


def _reconcile_footprint(
    footprint: str,
    old_copper: set[str],
    new_copper: list[str],
    decisions: KeepoutLayerIntents,
    used: set[str],
) -> str:
    intents, span = _read_intents(footprint)
    rules = _areas(footprint)
    identities = {rule.identity for rule in rules}
    if set(intents) - identities:
        raise ValueError(
            f"Stale {FIELD} provenance on {_reference(footprint)}; "
            "review the rule areas and provenance field before changing the stackup."
        )
    edits: list[tuple[int, int, str]] = []
    for rule in rules:
        intent = _resolve_rule_intent(footprint, rule, intents, decisions, used, old_copper)
        if intent != "all_copper":
            continue
        clause = "(layers " + " ".join(_sexpr_string(layer) for layer in new_copper) + ")"
        edits.append((rule.layer_start, rule.layer_end, clause))
    updated = _apply_edits(footprint, edits)
    if span is not None:
        _, span = _read_intents(updated)
    return _write_intents(updated, intents, span)


def reconcile_footprint_keepouts(
    board: str,
    old_copper: set[str],
    new_copper: list[str],
    decisions: KeepoutLayerIntents | None = None,
) -> str:
    """Change only proven all-copper footprint rule masks, before layer removal guards."""
    decisions = decisions or {}
    if old_copper == set(new_copper) and not decisions:
        return board
    used: set[str] = set()
    edits = []
    for name, start, end in iter_root_child_spans(board):
        if name != "footprint":
            continue
        footprint = board[start:end]
        updated = _reconcile_footprint(footprint, old_copper, new_copper, decisions, used)
        if updated != footprint:
            edits.append((start, end, updated))
    if unknown := set(decisions) - used:
        raise ValueError(f"Unknown footprint/rule identity: {', '.join(sorted(unknown))}.")
    return _apply_edits(board, edits)


def remap_cloned_rule_intents(footprint: str, uuid_map: dict[str, str]) -> str:
    """Keep copied footprint provenance bound to the cloned rule UUIDs."""
    intents, span = _read_intents(footprint)
    if not intents:
        return footprint
    identities = {rule.identity for rule in _areas(footprint)}
    remapped: KeepoutLayerIntents = {}
    for identity, intent in intents.items():
        new_identity = uuid_map.get(identity)
        if new_identity is None or new_identity not in identities or new_identity in remapped:
            raise ValueError(f"Cannot safely remap {FIELD} provenance on cloned footprint.")
        remapped[new_identity] = intent
    return _write_intents(footprint, remapped, span)
