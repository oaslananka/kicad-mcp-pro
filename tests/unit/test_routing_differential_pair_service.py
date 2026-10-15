from __future__ import annotations

from pathlib import Path

from kicad_mcp.routing.differential_pair_rules import (
    RoutingDifferentialPairService,
    build_differential_pair_rule,
    infer_diff_pair_base,
)


def test_infer_diff_pair_base_preserves_common_suffix_rules() -> None:
    assert infer_diff_pair_base("USB_DP", "USB_DN") == "USB"
    assert infer_diff_pair_base("CLK_P", "CLK_N") == "CLK"
    assert infer_diff_pair_base("LAN+", "LAN-") == "LAN"
    assert infer_diff_pair_base("NET_A", "NET_B") is None


def test_build_differential_pair_rule_preserves_legacy_body() -> None:
    name, body = build_differential_pair_rule("USB_DP", "USB_DN", 0.16, 0.18, 0.1)
    assert name == "Differential pair USB_DP USB_DN"
    assert body == "\n".join(
        [
            '(rule "Differential pair USB_DP USB_DN"',
            "  (condition \"A.inDiffPair('USB')\")",
            "  (constraint track_width (min 0.1600mm) (opt 0.1600mm) (max 0.1600mm))",
            "  (constraint diff_pair_gap (min 0.1800mm) (opt 0.1800mm) (max 0.1800mm))",
            "  (constraint skew (max 0.1000mm))",
            ")",
        ]
    )


def test_build_differential_pair_rule_preserves_explicit_net_fallback() -> None:
    _name, body = build_differential_pair_rule("NET_A", "NET_B", 0.2, 0.2, 0.1)
    assert "A.NetName == 'NET_A' || A.NetName == 'NET_B'" in body


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
