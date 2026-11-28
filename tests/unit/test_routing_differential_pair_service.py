from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.routing.differential_pair_rules import (
    RoutingDifferentialPairService,
    build_differential_pair_rule,
    infer_diff_pair_base,
)


@pytest.mark.parametrize(
    ("positive", "negative", "base"),
    [
        ("USB_DP", "USB_DN", "USB_D"),
        ("CLK_P", "CLK_N", "CLK_"),
        ("LAN+", "LAN-", "LAN"),
        ("/CLK_P0", "/CLK_N0", "/CLK_"),
        ("/CLK_P_12", "/CLK_N_12", "/CLK_"),
        ("/USB_D+", "/USB_D-", "/USB_D"),
        ("CLK_P0", "CLK_N1", None),
        ("USB_DP", "USB_DM", None),
        ("CLK_N", "CLK_P", None),
        ("CLK_P", "CLK_P", None),
        ("CLK+", "CLK_N", None),
        ("NET_A", "NET_B", None),
        ("USB1_P", "USB2_N", None),
    ],
)
def test_infer_native_pair_base(positive: str, negative: str, base: str | None) -> None:
    assert infer_diff_pair_base(positive, negative) == base


def test_build_differential_pair_rule_targets_only_requested_nets() -> None:
    name, body = build_differential_pair_rule("USB_DP", "USB_DN", 0.16, 0.18, 0.1)
    assert name == "Differential pair USB_DP USB_DN"
    assert body == "\n".join(
        [
            '(rule "Differential pair USB_DP USB_DN"',
            "  (condition \"A.NetName == 'USB_DP' || A.NetName == 'USB_DN'\")",
            "  (constraint track_width (min 0.1600mm) (opt 0.1600mm) (max 0.1600mm))",
            "  (constraint diff_pair_gap (min 0.1800mm) (opt 0.1800mm) (max 0.1800mm))",
            "  (constraint skew (max 0.1000mm))",
            ")",
        ]
    )


def test_numbered_pair_rule_does_not_match_sibling_pairs() -> None:
    _, body = build_differential_pair_rule("/CLK_P0", "/CLK_N0", 0.2, 0.2, 0.1)
    assert "A.NetName == '/CLK_P0' || A.NetName == '/CLK_N0'" in body
    assert "inDiffPair" not in body


@pytest.mark.parametrize(
    ("positive", "negative"),
    [
        ("NET_A", "NET_B"),
        ("USB_DP", "USB_DM"),
        ("CLK_P0", "CLK_N1"),
        ("CLK_N", "CLK_P"),
        ("CLK*_P", "CLK*_N"),
        ("CLK?_P", "CLK?_N"),
        ("CLK'_P", "CLK'_N"),
        ('CLK"_P', 'CLK"_N'),
        ("CLK\\_P", "CLK\\_N"),
        ("CLK\n_P", "CLK\n_N"),
    ],
)
def test_unsupported_pair_refuses_without_writing(positive: str, negative: str) -> None:
    with pytest.raises(ValueError, match="net names"):
        build_differential_pair_rule(positive, negative, 0.2, 0.2, 0.1)

    def unexpected_write(_name: str, _body: str) -> Path:
        pytest.fail("Unsupported pair must not write any rule")

    service = RoutingDifferentialPairService(
        list_board_net_names=lambda: {positive, negative},
        write_rule=unexpected_write,
    )
    result = service.set_pair(positive, negative)
    assert "not written" in result
    assert "schematic" in result
    assert "P/N" in result


def test_set_pair_preserves_missing_net_message() -> None:
    service = RoutingDifferentialPairService(
        list_board_net_names=lambda: {"USB_DP"},
        write_rule=lambda _name, _body: Path("unused.kicad_dru"),
    )
    assert service.set_pair("USB_DP", "USB_DN") == (
        "Differential-pair routing rule was not written. Missing nets: USB_DN"
    )


def test_set_pair_preserves_success_response(tmp_path: Path) -> None:
    calls: list[tuple[str, str]] = []
    path = tmp_path / "demo.kicad_dru"
    service = RoutingDifferentialPairService(
        list_board_net_names=lambda: {"USB_DP", "USB_DN"},
        write_rule=lambda name, body: calls.append((name, body)) or path,
    )
    result = service.set_pair("USB_DP", "USB_DN", "B_Cu", 0.16, 0.18, 0.12)
    assert calls
    assert calls[0][0] == "Differential pair USB_DP USB_DN"
    assert result == (
        f"Differential-pair routing rule 'Differential pair USB_DP USB_DN' written to {path}.\n"
        "Layer intent: B_Cu, width: 0.1600mm, gap: 0.1800mm, max skew: 0.1200mm."
    )


def test_set_pair_preserves_writer_failure_text() -> None:
    def fail(_name: str, _body: str) -> Path:
        raise ValueError("bad rules")

    service = RoutingDifferentialPairService(
        list_board_net_names=lambda: {"USB_DP", "USB_DN"},
        write_rule=fail,
    )
    assert service.set_pair("USB_DP", "USB_DN") == (
        "Differential-pair rule update failed: bad rules"
    )


@pytest.mark.parametrize("collision", ["/clk_P0", "/CLK_n0", "/clk_N0"])
def test_case_insensitive_board_name_collision_refuses_without_writing(collision: str) -> None:
    def unexpected_write(_name: str, _body: str) -> Path:
        pytest.fail("Ambiguous pair must not write any rule")

    service = RoutingDifferentialPairService(
        list_board_net_names=lambda: {"/CLK_P0", "/CLK_N0", collision},
        write_rule=unexpected_write,
    )
    result = service.set_pair("/CLK_P0", "/CLK_N0")
    assert "not written" in result
    assert "case-insensitive" in result
    assert "schematic" in result
