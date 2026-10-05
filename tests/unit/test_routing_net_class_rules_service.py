from __future__ import annotations

from pathlib import Path

from kicad_mcp.routing.net_class_rules import (
    RoutingNetClassRuleService,
    build_net_class_rule,
)
from kicad_mcp.utils.dru import iter_rule_nodes, parse_dru


def test_build_net_class_rule_preserves_legacy_body() -> None:
    name, body = build_net_class_rule("high_speed", 0.18, 0.15, 0.45, 0.2)

    assert name == "Net class high_speed"
    assert body == "\n".join(
        [
            '(rule "Net class high_speed"',
            "  (condition \"A.NetClass == 'high_speed'\")",
            "  (constraint track_width (min 0.1800mm) (opt 0.1800mm) (max 0.1800mm))",
            "  (constraint clearance (min 0.1500mm))",
            "  (constraint via_diameter (min 0.4500mm) (opt 0.4500mm) (max 0.4500mm))",
            "  (constraint via_drill (min 0.2000mm) (opt 0.2000mm) (max 0.2000mm))",
            ")",
        ]
    )


def test_build_net_class_rule_escapes_expression_and_sexpr_layers() -> None:
    net_class = "O'Brien\\critical"
    name, body = build_net_class_rule(net_class, 0.18, 0.15, 0.45, 0.2)

    root, _version = parse_dru(f"(rules\n{body}\n)\n")
    rule = iter_rule_nodes(root)[0]
    condition = next(
        child for child in rule if isinstance(child, list) and child and child[0] == "condition"
    )

    assert name == "Net class O'Brien\\critical"
    assert condition == ["condition", "A.NetClass == 'O\\'Brien\\\\critical'"]


def test_set_rules_preserves_success_response(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    path = tmp_path / "demo.kicad_dru"
    service = RoutingNetClassRuleService(
        write_rule=lambda name, body: calls.append((name, body)) or path
    )

    result = service.set_rules("high_speed", 0.18, 0.15, 0.45, 0.2)

    assert calls and calls[0][0] == "Net class high_speed"
    assert result == (
        f"Net-class routing rule 'Net class high_speed' written to {path}.\n"
        "Track width: 0.1800mm, clearance: 0.1500mm, "
        "via: 0.4500mm / drill 0.2000mm."
    )


def test_set_rules_preserves_writer_failure_text() -> None:
    def fail(_name: str, _body: str) -> Path:
        raise ValueError("bad rules")

    service = RoutingNetClassRuleService(write_rule=fail)

    assert service.set_rules("high_speed", 0.18, 0.15, 0.45, 0.2) == (
        "Net-class rule update failed: bad rules"
    )
