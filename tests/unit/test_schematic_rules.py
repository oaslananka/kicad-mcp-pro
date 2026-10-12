"""Unit tests for the pure electrical-design-rule engine (issue #197)."""

from __future__ import annotations

from kicad_mcp.utils.schematic_rules import (
    ethernet_pair_key,
    is_active_low_interrupt_name,
    is_bootstrap_name,
    is_can_name,
    is_external_port_name,
    is_feedback_name,
    is_ground_name,
    is_i2c_name,
    is_reset_name,
    is_supply_rail_name,
    is_usb_cc_name,
    merge_nets_by_name,
    rail_voltage,
    run_schematic_design_rules,
    usb_data_polarity,
)


def _net(names: list[str], pins: list[tuple[str, str]]) -> dict:
    return {
        "names": names,
        "pins": [{"reference": ref, "pin": pin, "value": ""} for ref, pin in pins],
    }


def _net_v(names: list[str], pins: list[tuple[str, str, str]]) -> dict:
    return {
        "names": names,
        "pins": [{"reference": ref, "pin": pin, "value": value} for ref, pin, value in pins],
    }


def test_supply_rail_classification() -> None:
    for name in ["VCC", "VDD", "+3V3", "+5V", "3V3", "5V", "VBAT", "AVDD", "+12V"]:
        assert is_supply_rail_name(name), name
    for name in ["GND", "AGND", "VSS", "0V", "SDA", "NET1"]:
        assert not is_supply_rail_name(name), name


def test_supply_rail_classification_suffixed_and_compound_names() -> None:
    # Common project naming with a domain suffix or an embedded voltage token
    # (e.g. SismoSmart's rails) must still read as supply rails.
    for name in ["3V3_DIG", "3V3_ANA", "5V_SYS", "VBUS_5V", "VPOE_5V", "3V3-DIG"]:
        assert is_supply_rail_name(name), name
    # A plain numeric domain suffix is not a rail (no V token).
    for name in ["GPIO_5", "BANK_12", "SPI_SCLK", "CS_ADXL", "DATA0"]:
        assert not is_supply_rail_name(name), name


def test_rail_voltage_parses_embedded_voltage_token() -> None:
    assert rail_voltage("3V3_DIG") == 3.3
    assert rail_voltage("3V3_ANA") == 3.3
    assert rail_voltage("5V_SYS") == 5.0
    assert rail_voltage("VBUS_5V") == 5.0
    assert rail_voltage("VPOE_5V") == 5.0
    assert rail_voltage("VBAT") is None  # named rail, no explicit voltage
    assert rail_voltage("GPIO_5") is None


def test_ground_and_i2c_classification() -> None:
    assert is_ground_name("GND")
    assert is_ground_name("agnd")
    assert is_i2c_name("SDA")
    assert is_i2c_name("I2C_SCL")
    assert is_i2c_name("SENSOR_SDA")
    assert not is_i2c_name("SDATA")
    assert not is_i2c_name("VCC")


def test_merge_nets_by_name_unions_cross_sheet_named_nets() -> None:
    nets = [
        _net(["VCC"], [("U1", "1")]),
        _net(["VCC"], [("C1", "1")]),
        _net([], [("R9", "2")]),
    ]
    merged = merge_nets_by_name(nets)
    vcc = [n for n in merged if "VCC" in n["names"]]
    assert len(vcc) == 1
    refs = {p["reference"] for p in vcc[0]["pins"]}
    assert refs == {"U1", "C1"}
    # Unnamed groups pass through untouched.
    assert any(n["names"] == [] for n in merged)


def test_i2c_without_pullup_is_flagged_and_with_pullup_is_clean() -> None:
    flagged = run_schematic_design_rules([_net(["I2C_SDA"], [("U1", "5")])])
    assert any(f.rule_id == "i2c_pullups" for f in flagged)

    clean = run_schematic_design_rules([_net(["I2C_SDA"], [("U1", "5"), ("R1", "1")])])
    assert not any(f.rule_id == "i2c_pullups" for f in clean)


def test_supply_rail_without_decoupling_is_flagged() -> None:
    flagged = run_schematic_design_rules([_net(["+3V3"], [("U1", "1")])])
    decoupling = [f for f in flagged if f.rule_id == "power_rail_decoupling"]
    assert len(decoupling) == 1
    assert "U1" in decoupling[0].refs


def test_supply_rail_with_cap_or_without_ic_is_clean() -> None:
    with_cap = run_schematic_design_rules([_net(["+3V3"], [("U1", "1"), ("C1", "1")])])
    assert not any(f.rule_id == "power_rail_decoupling" for f in with_cap)

    # A rail with no IC on it (e.g. just a connector) is not flagged for decoupling.
    no_ic = run_schematic_design_rules([_net(["+3V3"], [("J1", "2"), ("C1", "1")])])
    assert not any(f.rule_id == "power_rail_decoupling" for f in no_ic)

    # Ground is never flagged as needing decoupling.
    gnd = run_schematic_design_rules([_net(["GND"], [("U1", "8")])])
    assert not any(f.rule_id == "power_rail_decoupling" for f in gnd)


def test_reset_name_classification() -> None:
    for name in ["NRST", "RESET", "~RESET", "MCU_RST", "RESET_N", "MCLR"]:
        assert is_reset_name(name), name
    for name in ["BURST", "VCC", "SDA", "FIRST"]:
        assert not is_reset_name(name), name


def test_reset_line_without_pull_resistor_is_flagged() -> None:
    flagged = run_schematic_design_rules([_net(["NRST"], [("U1", "7")])])
    reset = [f for f in flagged if f.rule_id == "reset_pullup"]
    assert len(reset) == 1
    assert "U1" in reset[0].refs

    with_r = run_schematic_design_rules([_net(["NRST"], [("U1", "7"), ("R1", "1")])])
    assert not any(f.rule_id == "reset_pullup" for f in with_r)

    # A reset-named net that does not reach an IC is not flagged.
    no_ic = run_schematic_design_rules([_net(["NRST"], [("J1", "3")])])
    assert not any(f.rule_id == "reset_pullup" for f in no_ic)


def test_crystal_without_load_caps_is_flagged() -> None:
    nets = [
        _net(["XIN"], [("Y1", "1"), ("U1", "5")]),
        _net(["XOUT"], [("Y1", "2"), ("U1", "6")]),
    ]
    flagged = run_schematic_design_rules(nets)
    crystal = [f for f in flagged if f.rule_id == "crystal_load_caps"]
    assert len(crystal) == 1
    assert crystal[0].refs == ("Y1",)

    with_caps = run_schematic_design_rules(
        [
            _net(["XIN"], [("Y1", "1"), ("C1", "1")]),
            _net(["XOUT"], [("Y1", "2"), ("C2", "1")]),
        ]
    )
    assert not any(f.rule_id == "crystal_load_caps" for f in with_caps)


def _supply_net(name: str, pins: list[tuple[str, str, str]]) -> dict:
    return {
        "names": [name],
        "pins": [{"reference": r, "pin": p, "etype": e} for r, p, e in pins],
    }


def test_decoupling_count_flags_partial_decoupling() -> None:
    nets = [
        _supply_net(
            "+3V3",
            [("U1", "1", "power_in"), ("U1", "2", "power_in"), ("C1", "1", "passive")],
        )
    ]
    flagged = [f for f in run_schematic_design_rules(nets) if f.rule_id == "decoupling_count"]
    assert len(flagged) == 1
    assert flagged[0].refs == ("U1",)


def test_decoupling_count_clean_when_caps_match_pins() -> None:
    nets = [
        _supply_net(
            "+3V3",
            [
                ("U1", "1", "power_in"),
                ("U1", "2", "power_in"),
                ("C1", "1", "passive"),
                ("C2", "1", "passive"),
            ],
        )
    ]
    assert not any(f.rule_id == "decoupling_count" for f in run_schematic_design_rules(nets))


def test_decoupling_count_defers_to_rail_rule_when_zero_caps() -> None:
    found = run_schematic_design_rules([_supply_net("+3V3", [("U1", "1", "power_in")])])
    assert any(f.rule_id == "power_rail_decoupling" for f in found)
    assert not any(f.rule_id == "decoupling_count" for f in found)


def test_pin_records_capture_electrical_type() -> None:
    from kicad_mcp.tools.schematic import _extract_pin_records

    block = (
        '(symbol "U_1_1"'
        " (pin power_in line (at -10.16 0 0) (length 2.54)"
        ' (name "VDD" (effects (font (size 1.27 1.27))))'
        ' (number "1" (effects (font (size 1.27 1.27)))))'
        " (pin input line (at 10.16 0 180) (length 2.54)"
        ' (name "IN" (effects (font (size 1.27 1.27))))'
        ' (number "2" (effects (font (size 1.27 1.27))))))'
    )
    records = {r["number"]: r for r in _extract_pin_records(block)}
    assert records["1"]["etype"] == "power_in"
    assert records["1"]["name"] == "VDD"
    assert records["2"]["etype"] == "input"


def test_can_and_interrupt_classification() -> None:
    assert is_can_name("CANH")
    assert is_can_name("CAN_L")
    assert is_can_name("CAN-H")
    assert not is_can_name("VCAN")
    assert not is_can_name("SCAN")
    assert is_active_low_interrupt_name("NINT")
    assert is_active_low_interrupt_name("INT_N")
    assert is_active_low_interrupt_name("~IRQ")
    assert is_active_low_interrupt_name("MCU_IRQ_N")
    assert not is_active_low_interrupt_name("INT")  # active-high, not flagged
    assert not is_active_low_interrupt_name("PRINT")
    assert not is_active_low_interrupt_name("POINT_N")


def _net_e(names: list[str], pins: list[tuple[str, str, str]]) -> dict:
    return {
        "names": names,
        "pins": [{"reference": r, "pin": p, "etype": e} for r, p, e in pins],
    }


def test_no_connect_pin_wired_is_flagged() -> None:
    wired = run_schematic_design_rules(
        [_net_e(["NET1"], [("U1", "3", "no_connect"), ("U2", "1", "input")])]
    )
    nc = [f for f in wired if f.rule_id == "nc_pin_connected"]
    assert len(nc) == 1
    assert nc[0].refs == ("U1",)

    # An NC pin alone on its own net is fine.
    alone = run_schematic_design_rules([_net_e([], [("U1", "3", "no_connect")])])
    assert not any(f.rule_id == "nc_pin_connected" for f in alone)


def test_can_bus_without_termination_is_flagged() -> None:
    flagged = run_schematic_design_rules([_net(["CANH"], [("U1", "5"), ("J1", "1")])])
    assert any(f.rule_id == "can_bus_termination" for f in flagged)
    with_r = run_schematic_design_rules([_net(["CANH"], [("U1", "5"), ("R1", "1")])])
    assert not any(f.rule_id == "can_bus_termination" for f in with_r)


def test_active_low_interrupt_without_pullup_is_flagged() -> None:
    flagged = run_schematic_design_rules([_net(["NINT"], [("U1", "12")])])
    assert any(f.rule_id == "interrupt_pullup" for f in flagged)
    with_r = run_schematic_design_rules([_net(["NINT"], [("U1", "12"), ("R1", "1")])])
    assert not any(f.rule_id == "interrupt_pullup" for f in with_r)
    # Active-high INT is not flagged.
    active_high = run_schematic_design_rules([_net(["INT"], [("U1", "12")])])
    assert not any(f.rule_id == "interrupt_pullup" for f in active_high)


def test_design_rule_check_tool_is_declared_in_validation_category() -> None:
    from kicad_mcp.tools.router import TOOL_CATEGORIES

    assert "schematic_design_rule_check" in TOOL_CATEGORIES["validation"]["tools"]


def test_rail_voltage_parsing() -> None:
    assert rail_voltage("+3V3") == 3.3
    assert rail_voltage("3V3") == 3.3
    assert rail_voltage("3.3V") == 3.3
    assert rail_voltage("+5V") == 5.0
    assert rail_voltage("+1V8") == 1.8
    assert rail_voltage("+12V") == 12.0
    # Value-less aliases carry no comparable voltage.
    assert rail_voltage("VCC") is None
    assert rail_voltage("VBUS") is None
    assert rail_voltage("GND") is None


def test_conflicting_supply_rails_on_one_net_is_flagged() -> None:
    flagged = run_schematic_design_rules([_net(["+3V3", "+5V"], [("U1", "1")])])
    conflict = [f for f in flagged if f.rule_id == "conflicting_supply_rails"]
    assert len(conflict) == 1
    assert conflict[0].severity == "error"
    assert "+3V3" in conflict[0].message
    assert "+5V" in conflict[0].message
    assert conflict[0].refs == ("U1",)


def test_consistent_rail_aliases_are_not_flagged() -> None:
    # Same voltage written two ways is consistent, not a conflict.
    same = run_schematic_design_rules([_net(["+3V3", "3V3"], [("U1", "1")])])
    assert not any(f.rule_id == "conflicting_supply_rails" for f in same)

    # A value-less alias next to a numeric rail cannot be compared by value.
    aliased = run_schematic_design_rules([_net(["VCC", "+5V"], [("U1", "1")])])
    assert not any(f.rule_id == "conflicting_supply_rails" for f in aliased)

    # A single rail is always clean.
    single = run_schematic_design_rules([_net(["+3V3"], [("U1", "1"), ("C1", "1")])])
    assert not any(f.rule_id == "conflicting_supply_rails" for f in single)


def test_usb_data_polarity_classification() -> None:
    # Sign forms anywhere; letter forms only with a USB prefix.
    for name in ["D+", "USB_DP", "USB_D+", "USB_D_P", "USB DP"]:
        assert usb_data_polarity(name) == "+", name
    for name in ["D-", "USB_DM", "USB_D-", "USB_D_N", "USB DM"]:
        assert usb_data_polarity(name) == "-", name
    # Ambiguous bare letter forms and non-USB names — including DDR data-mask
    # lines — must not be mistaken for a USB pair.
    for name in ["DATA", "VCC", "GND", "DDR_DM", "DQM0", "SDRAM_DM1", "ADDR", "DP", "DM", "VDD+"]:
        assert usb_data_polarity(name) is None, name


def test_usb_cc_classification() -> None:
    for name in ["CC", "CC1", "CC2", "USB_CC1", "USBC_CC2"]:
        assert is_usb_cc_name(name), name
    for name in ["VCC", "AVCC", "ACC", "SUCCESS", "CCD"]:
        assert not is_usb_cc_name(name), name


def test_usb_diff_pair_half_is_flagged_and_complete_pair_is_clean() -> None:
    # Only D+ wired -> the missing D- half is flagged once.
    half = run_schematic_design_rules([_net(["USB_DP"], [("J1", "3"), ("U1", "10")])])
    pair = [f for f in half if f.rule_id == "usb_diff_pair_complete"]
    assert len(pair) == 1
    assert "D-" in pair[0].message
    assert set(pair[0].refs) == {"J1", "U1"}

    # Both halves present on their own nets -> clean.
    complete = run_schematic_design_rules(
        [_net(["USB_DP"], [("J1", "3")]), _net(["USB_DM"], [("J1", "2")])]
    )
    assert not any(f.rule_id == "usb_diff_pair_complete" for f in complete)

    # No USB data nets at all -> nothing to say.
    none = run_schematic_design_rules([_net(["+3V3"], [("U1", "1"), ("C1", "1")])])
    assert not any(f.rule_id == "usb_diff_pair_complete" for f in none)


def test_usbc_cc_resistor_is_required_and_resistor_clears_it() -> None:
    flagged = run_schematic_design_rules([_net(["CC1"], [("J1", "5"), ("U1", "1")])])
    cc = [f for f in flagged if f.rule_id == "usbc_cc_resistors"]
    assert len(cc) == 1
    assert set(cc[0].refs) == {"J1", "U1"}

    with_r = run_schematic_design_rules([_net(["CC1"], [("J1", "5"), ("R1", "1")])])
    assert not any(f.rule_id == "usbc_cc_resistors" for f in with_r)

    # A CC net with no part on it (stray label) is not flagged.
    stray = run_schematic_design_rules([_net(["CC2"], [("TP1", "1")])])
    assert not any(f.rule_id == "usbc_cc_resistors" for f in stray)


def test_ethernet_pair_key_classification() -> None:
    assert ethernet_pair_key("TX+") == ("TX", "P")
    assert ethernet_pair_key("TX-") == ("TX", "N")
    assert ethernet_pair_key("MDI0_P") == ("MDI0", "P")
    assert ethernet_pair_key("MDI0_N") == ("MDI0", "N")
    assert ethernet_pair_key("ETH_TX_P") == ("TX", "P")
    assert ethernet_pair_key("TRD1-") == ("TRD1", "N")
    assert ethernet_pair_key("RX0_N") == ("RX0", "N")
    # Single-ended UART / MII control lines carry no polarity -> not a pair.
    for name in ["TX", "RX", "TXD", "RXD0", "TXEN", "RX_DV", "RXER", "DATA", "VCC"]:
        assert ethernet_pair_key(name) is None, name


def test_ethernet_incomplete_lane_is_flagged_and_complete_is_clean() -> None:
    # Only TX+ present -> the missing TX- half is flagged once.
    half = run_schematic_design_rules([_net(["ETH_TX_P"], [("U1", "1"), ("J1", "2")])])
    eth = [f for f in half if f.rule_id == "ethernet_diff_pair"]
    assert len(eth) == 1
    assert "TX-" in eth[0].message
    assert set(eth[0].refs) == {"U1", "J1"}

    # Both halves present -> clean.
    full = run_schematic_design_rules([_net(["TX+"], [("U1", "1")]), _net(["TX-"], [("U1", "2")])])
    assert not any(f.rule_id == "ethernet_diff_pair" for f in full)

    # Single-ended UART TX/RX must never be flagged as a half-pair.
    uart = run_schematic_design_rules([_net(["TX"], [("U1", "1")]), _net(["RX"], [("U1", "2")])])
    assert not any(f.rule_id == "ethernet_diff_pair" for f in uart)


def test_external_port_name_classification() -> None:
    for name in ["USB_DP", "CC1", "CANH", "ETH_TX_P", "RS485_A", "UART_TXD", "VBUS", "VIN"]:
        assert is_external_port_name(name), name
    for name in ["+3V3", "VCC", "RESET", "LED_A", "SENSOR_SDA"]:
        assert not is_external_port_name(name), name


def test_external_port_without_protection_is_flagged_and_protection_clears_it() -> None:
    flagged = run_schematic_design_rules([_net(["USB_DP"], [("J1", "3"), ("U1", "10")])])
    protection = [f for f in flagged if f.rule_id == "external_port_protection"]
    assert len(protection) == 1
    assert protection[0].refs == ("J1", "U1")
    assert "ESD/TVS" in protection[0].message

    with_esd = run_schematic_design_rules(
        [_net_v(["USB_DP"], [("J1", "3", ""), ("U1", "10", ""), ("D1", "1", "ESD9M5V")])]
    )
    assert not any(f.rule_id == "external_port_protection" for f in with_esd)

    with_fuse = run_schematic_design_rules(
        [_net_v(["VBUS"], [("J1", "1", ""), ("U1", "5", ""), ("F1", "1", "polyfuse")])]
    )
    assert not any(f.rule_id == "external_port_protection" for f in with_fuse)


def test_external_port_protection_ignores_connector_only_and_internal_nets() -> None:
    connector_only = run_schematic_design_rules([_net(["USB_DP"], [("J1", "3")])])
    assert not any(f.rule_id == "external_port_protection" for f in connector_only)

    internal = run_schematic_design_rules([_net(["SENSOR_SDA"], [("U1", "3"), ("U2", "5")])])
    assert not any(f.rule_id == "external_port_protection" for f in internal)


def test_smps_bootstrap_and_feedback_classification() -> None:
    for name in ["BST", "VBST", "SW_BST", "BOOTSTRAP", "BUCK_BST"]:
        assert is_bootstrap_name(name), name
    # MCU boot-mode straps and unrelated words must not look like a bootstrap node.
    for name in ["BOOT0", "BOOT1", "BOOTSEL", "BURST", "ROBUST", "VCC"]:
        assert not is_bootstrap_name(name), name

    for name in ["FB", "VFB", "FEEDBACK", "BUCK_FB", "FB_SENSE"]:
        assert is_feedback_name(name), name
    for name in ["FBGA", "AFB", "VCC", "GND"]:
        assert not is_feedback_name(name), name


def test_smps_bootstrap_cap_is_required_and_cap_clears_it() -> None:
    flagged = run_schematic_design_rules([_net(["SW_BST"], [("U1", "3")])])
    bst = [f for f in flagged if f.rule_id == "smps_bootstrap_cap"]
    assert len(bst) == 1
    assert bst[0].refs == ("U1",)

    with_cap = run_schematic_design_rules([_net(["SW_BST"], [("U1", "3"), ("C1", "1")])])
    assert not any(f.rule_id == "smps_bootstrap_cap" for f in with_cap)

    # A BST-named net that reaches no IC is not flagged.
    no_ic = run_schematic_design_rules([_net(["BST"], [("J1", "1")])])
    assert not any(f.rule_id == "smps_bootstrap_cap" for f in no_ic)


def test_smps_feedback_divider_is_required_and_resistor_clears_it() -> None:
    flagged = run_schematic_design_rules([_net(["VFB"], [("U1", "4")])])
    fb = [f for f in flagged if f.rule_id == "smps_feedback_divider"]
    assert len(fb) == 1
    assert fb[0].refs == ("U1",)

    with_r = run_schematic_design_rules([_net(["VFB"], [("U1", "4"), ("R1", "1")])])
    assert not any(f.rule_id == "smps_feedback_divider" for f in with_r)


def test_findings_are_sorted_and_typed() -> None:
    findings = run_schematic_design_rules(
        [
            _net(["+3V3"], [("U1", "1")]),
            _net(["I2C_SCL"], [("U1", "6")]),
        ]
    )
    assert {f.rule_id for f in findings} == {"power_rail_decoupling", "i2c_pullups"}
    assert all(f.severity in {"error", "warning", "info"} for f in findings)
    # Stable ordering by (severity, rule_id, message).
    assert findings == sorted(findings, key=lambda f: f.sort_key())
