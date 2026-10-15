from __future__ import annotations

from pathlib import Path

from kicad_mcp.routing.length_tuning import (
    RoutingLengthTuningService,
    build_diff_pair_length_rules,
    build_length_tune_rule,
)


def test_build_length_tune_rule_preserves_legacy_body() -> None:
    name, body = build_length_tune_rule("CLK", 45.0, 0.2)

    assert name == "Length tune CLK"
    assert body == "\n".join(
        [
            '(rule "Length tune CLK"',
            "  (condition \"A.NetName == 'CLK'\")",
            "  (constraint length (min 44.8000mm) (opt 45.0000mm) (max 45.2000mm))",
            ")",
        ]
    )


def test_build_diff_pair_length_rules_preserves_legacy_bodies() -> None:
    rules = build_diff_pair_length_rules("USB_DP", "USB_DN", 50.0)

    assert [name for name, _body in rules] == [
        "Length tune USB_DP",
        "Length tune USB_DN",
        "Length match USB_DP USB_DN",
    ]
    assert "constraint skew (max 0.1000mm)" in rules[-1][1]


def _service(
    *,
    nets: set[str],
    lengths: dict[str, float] | None = None,
    write_rule=None,
) -> RoutingLengthTuningService:
    lengths = lengths or {}
    writer = write_rule or (lambda name, _body: Path(f"{name}.kicad_dru"))
    return RoutingLengthTuningService(
        list_board_net_names=lambda: nets,
        current_track_length_mm=lambda net: lengths.get(net, 0.0),
        write_rule=writer,
    )


def test_tune_net_preserves_missing_net_message() -> None:
    service = _service(nets={"DATA0"})

    assert service.tune_net("CLK", 45.0) == (
        "Length-tuning rule was not written. Net 'CLK' was not found on the active board."
    )


def test_tune_net_preserves_success_response_and_status(tmp_path: Path) -> None:
    path = tmp_path / "demo.kicad_dru"
    calls: list[tuple[str, str]] = []
    service = _service(
        nets={"CLK"},
        lengths={"CLK": 42.0},
        write_rule=lambda name, body: calls.append((name, body)) or path,
    )

    result = service.tune_net("CLK", 45.0, 0.75, 0.2)

    assert calls
    assert calls[0][0] == "Length tune CLK"
    assert result == (
        f"Length-tuning rule 'Length tune CLK' written to {path}.\n"
        "Current length: 42.000 mm\n"
        "Target length: 45.000 mm\n"
        "Delta: 3.000 mm (needs tuning)\n"
        "Suggested meander amplitude: 0.750 mm"
    )


def test_tune_net_preserves_writer_failure_text() -> None:
    def fail(_name: str, _body: str) -> Path:
        raise ValueError("bad rules")

    service = _service(nets={"CLK"}, write_rule=fail)

    assert service.tune_net("CLK", 45.0) == "Length-tuning rule update failed: bad rules"


def test_tune_diff_pair_preserves_missing_net_order() -> None:
    service = _service(nets={"USB_DP"})

    assert service.tune_diff_pair("USB_DP", "NOPE", 50.0) == (
        "Differential-pair length tuning rules were not written. Missing nets: NOPE"
    )


def test_tune_diff_pair_preserves_success_response_and_rule_order(tmp_path: Path) -> None:
    path = tmp_path / "demo.kicad_dru"
    calls: list[tuple[str, str]] = []
    service = _service(
        nets={"USB_DP", "USB_DN"},
        lengths={"USB_DP": 50.0, "USB_DN": 50.4},
        write_rule=lambda name, body: calls.append((name, body)) or path,
    )

    result = service.tune_diff_pair("USB_DP", "USB_DN", 51.0)

    assert [name for name, _body in calls] == [
        "Length tune USB_DP",
        "Length tune USB_DN",
        "Length match USB_DP USB_DN",
    ]
    assert result == (
        "Differential-pair length rules updated.\n"
        f"Rules file: {path}\n"
        "USB_DP: 50.000 mm\n"
        "USB_DN: 50.400 mm\n"
        "Current skew: 0.400 mm\n"
        "Target length: 51.000 mm"
    )


def test_tune_diff_pair_preserves_writer_failure_text() -> None:
    calls = 0

    def fail_second(_name: str, _body: str) -> Path:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        return Path("demo.kicad_dru")

    service = _service(
        nets={"USB_DP", "USB_DN"},
        write_rule=fail_second,
    )

    assert service.tune_diff_pair("USB_DP", "USB_DN", 51.0) == (
        "Differential-pair length tuning failed: disk full"
    )
