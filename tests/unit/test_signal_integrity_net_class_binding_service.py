from __future__ import annotations

from kicad_mcp.signal_integrity.net_class_binding import (
    SignalIntegrityNetClassBindingService,
)


def test_bind_dry_run_preserves_plan_output_and_skips_writer() -> None:
    calls: list[tuple[object, ...]] = []

    def writer(name: str, clearance: float, width: float, gap: float | None) -> str:
        calls.append((name, clearance, width, gap))
        return "fixture.kicad_dru"

    result = SignalIntegrityNetClassBindingService().bind(
        interfaces=[
            {
                "kind": "usb3",
                "differential": True,
                "impedance_target_ohm": 90,
                "net_prefix": "USB_",
            },
            {"kind": "i2c"},
        ],
        dry_run=True,
        rule_writer=writer,
    )

    assert calls == []
    assert result.startswith("## Net Class Binding Plan\n")
    assert "### USB3" in result
    assert "- Clearance: 0.12 mm" in result
    assert "- Track width: 0.18 mm" in result
    assert "- Diff-pair gap: 0.15 mm" in result
    assert "- Impedance target: 90 ohm" in result
    assert "- Net prefix filter: USB_" in result
    assert "pcb_set_net_class(net_class='USB3', clearance=0.12, track_width=0.18)" in result
    assert "_Dry-run mode: no changes applied." in result
    assert "I2C" not in result


def test_bind_apply_preserves_writer_calls_and_error_reporting() -> None:
    calls: list[tuple[object, ...]] = []

    def writer(name: str, clearance: float, width: float, gap: float | None) -> str:
        calls.append((name, clearance, width, gap))
        if name == "PCIE_G4":
            raise RuntimeError("fixture failure")
        return "project.kicad_dru"

    result = SignalIntegrityNetClassBindingService().bind(
        interfaces=[
            {"kind": "usb2", "differential": True},
            {"kind": "pcie_g4", "differential": True},
        ],
        dry_run=False,
        rule_writer=writer,
    )

    assert calls == [
        ("USB2", 0.15, 0.2, 0.2),
        ("PCIE_G4", 0.08, 0.12, 0.1),
    ]
    assert "**Applied** 1 net class rule(s) to `project.kicad_dru`:" in result
    assert "  - USB2" in result
    assert "**Errors** (1):" in result
    assert "  - PCIE_G4: fixture failure" in result


def test_bind_reports_when_no_high_speed_interfaces_exist() -> None:
    result = SignalIntegrityNetClassBindingService().bind(
        interfaces=[{"kind": "i2c"}, {"kind": "uart"}],
        dry_run=False,
        rule_writer=lambda *_args: "unused.kicad_dru",
    )

    assert result == "No high-speed interfaces found that require custom net classes."
