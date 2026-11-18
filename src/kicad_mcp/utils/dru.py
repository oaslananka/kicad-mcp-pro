"""Helpers for reading and writing KiCad ``.kicad_dru`` rule files."""

from __future__ import annotations

import re
from typing import cast

from .sexpr import _sexpr_string

type SExprAtom = str
type SExprNode = list[SExprValue]
type SExprValue = SExprAtom | SExprNode

_SAFE_ATOM = re.compile(r"^[A-Za-z0-9_+./:-]+$")


def _consume_string_token(content: str, start: int) -> tuple[str, int]:
    cursor = start + 1
    escaped = False
    buffer: list[str] = []
    while cursor < len(content):
        current = content[cursor]
        if escaped:
            buffer.append(current)
            escaped = False
        elif current == "\\":
            escaped = True
        elif current == '"':
            return "".join(buffer), cursor + 1
        else:
            buffer.append(current)
        cursor += 1
    raise ValueError("Unterminated string literal in .kicad_dru content.")


def _consume_atom_token(content: str, start: int) -> tuple[str, int]:
    cursor = start
    while (
        cursor < len(content)
        and not content[cursor].isspace()
        and content[cursor] not in {"(", ")"}
    ):
        cursor += 1
    return content[start:cursor], cursor


def _tokenize(content: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    while index < len(content):
        char = content[index]
        if char.isspace():
            index += 1
        elif char == "#":
            end = content.find("\n", index)
            index = len(content) if end < 0 else end + 1
        elif char in {"(", ")"}:
            tokens.append(char)
            index += 1
        elif char == '"':
            token, index = _consume_string_token(content, index)
            tokens.append(token)
        else:
            token, index = _consume_atom_token(content, index)
            tokens.append(token)
    return tokens


def _parse_expression(tokens: list[str], start_index: int = 0) -> tuple[SExprValue, int]:
    current_item = tokens[start_index]
    if current_item != "(":
        return current_item, start_index + 1

    index = start_index + 1
    result: SExprNode = []
    while index < len(tokens):
        current_item = tokens[index]
        if current_item == ")":
            return result, index + 1
        child, index = _parse_expression(tokens, index)
        result.append(child)
    raise ValueError("Unbalanced parentheses in .kicad_dru content.")


def parse_dru(content: str) -> tuple[SExprNode, str | None]:
    """Parse native KiCad files into an internal rules tree.

    A native file starts with a version form and then has independent rule forms.
    The historical rules wrapper is accepted for migration on the next write.
    """
    tokens = _tokenize(content)
    if not tokens:
        return ["rules"], None

    index = 0
    version: str | None = None
    if len(tokens) >= 4 and tokens[:2] == ["(", "version"]:
        if tokens[3] != ")":
            raise ValueError("Malformed KiCad custom rule version declaration.")
        version = tokens[2]
        if version != "1":
            raise ValueError(f"Unsupported KiCad custom rule version {version!r}; expected 1.")
        index = 4

    root: SExprNode = ["rules"]
    if index >= len(tokens):
        return root, version

    while index < len(tokens):
        form, index = _parse_expression(tokens, index)
        if not isinstance(form, list) or not form:
            raise ValueError("A KiCad .kicad_dru root must contain rule forms.")
        if form[0] == "rules":
            if len(root) > 1 or index != len(tokens):
                raise ValueError("Legacy .kicad_dru rules wrapper must be the only root form.")
            if any(
                not isinstance(child, list) or not child or child[0] != "rule" for child in form[1:]
            ):
                raise ValueError("Legacy .kicad_dru rules wrapper contains an invalid rule.")
            return form, version
        if form[0] != "rule":
            raise ValueError("A KiCad .kicad_dru root must contain rule forms.")
        root.append(form)

    if version is None:
        raise ValueError("Native KiCad .kicad_dru requires a leading (version 1).")
    return root, version


def _format_atom(value: str) -> str:
    return value if _SAFE_ATOM.fullmatch(value) else _sexpr_string(value)


def _dump_expression(node: SExprValue, indent: int = 0) -> str:
    if not isinstance(node, list):
        return _format_atom(node)
    if not node:
        return "()"

    prefix_parts: list[str] = []
    child_index = 0
    while child_index < len(node) and not isinstance(node[child_index], list):
        value = cast(str, node[child_index])
        if node[0] == "rule" and child_index == 1:
            prefix_parts.append(_sexpr_string(value))
        else:
            prefix_parts.append(_format_atom(value))
        child_index += 1

    indent_text = "  " * indent
    if child_index >= len(node):
        return f"{indent_text}({' '.join(prefix_parts)})"

    lines = [f"{indent_text}({' '.join(prefix_parts)}"]
    for child in node[child_index:]:
        if isinstance(child, list):
            lines.append(_dump_expression(child, indent + 1))
        else:
            lines[-1] += " " + _format_atom(child)
    lines[-1] += ")"
    return "\n".join(lines)


def dump_dru(node: SExprNode, version: str | None = None) -> str:
    """Serialize native KiCad version header and top-level custom rules."""
    if not node or node[0] != "rules":
        raise ValueError("Expected an internal rules tree.")
    if version not in {None, "1"}:
        raise ValueError(f"Unsupported KiCad custom rule version {version!r}; expected 1.")
    rules = node[1:]
    if any(not isinstance(rule, list) or not rule or rule[0] != "rule" for rule in rules):
        raise ValueError("Invalid rule node in KiCad custom rules tree.")
    return "(version 1)\n" + "".join(_dump_expression(rule) + "\n" for rule in rules)


def iter_rule_nodes(root: SExprNode) -> list[SExprNode]:
    """Return every ``(rule ...)`` node from the supplied ``(rules ...)`` tree."""
    return [child for child in root[1:] if isinstance(child, list) and child and child[0] == "rule"]


def rule_name(rule: SExprNode) -> str:
    """Return the name of a parsed ``(rule ...)`` node."""
    if len(rule) < 2 or isinstance(rule[1], list):
        raise ValueError("Rule nodes must include a quoted name.")
    return rule[1]


def find_rule(root: SExprNode, name: str) -> SExprNode | None:
    """Look up a rule by name."""
    return next((rule for rule in iter_rule_nodes(root) if rule_name(rule) == name), None)


def upsert_rule(root: SExprNode, rule: SExprNode) -> SExprNode:
    """Insert or replace a rule inside the parsed ``(rules ...)`` tree."""
    name = rule_name(rule)
    for index, child in enumerate(root[1:], start=1):
        if isinstance(child, list) and child and child[0] == "rule" and rule_name(child) == name:
            root[index] = rule
            return root
    root.append(rule)
    return root


def delete_rule(root: SExprNode, name: str) -> bool:
    """Delete a rule by name, returning ``True`` when one was removed."""
    for index, child in enumerate(root[1:], start=1):
        if isinstance(child, list) and child and child[0] == "rule" and rule_name(child) == name:
            del root[index]
            return True
    return False
