"""Regression coverage for semantic IR connectivity grouping and net merging."""

from kicad_mcp.ir.circuit_ir import IRCircuit, IRNet
from kicad_mcp.ir.from_kicad import _net_group_connections, _populate_nets, _store_ir_net_group


def test_net_group_connections_filters_missing_pin_identifiers_and_deduplicates() -> None:
    pins = [
        {"reference": "R1", "pin": 1},
        {"reference": "R1", "pin": "1"},
        {"reference": "R2", "pin": 2},
        {"reference": "", "pin": "3"},
        {"reference": "U1", "pin": ""},
    ]
    assert {("R1", "1"), ("R2", "2")} == _net_group_connections(pins)


def test_populate_nets_merges_named_groups_without_losing_voltage_or_class() -> None:
    circuit = IRCircuit()
    circuit.nets["VCC"] = IRNet(
        name="VCC",
        connections=frozenset({("U1", "1")}),
        is_power=True,
        voltage=3.3,
        net_class="Power",
    )
    groups = [
        {"names": ["VCC"], "pins": [{"reference": "R1", "pin": "2"}]},
        {"names": ["VCC"], "pins": [{"reference": "R2", "pin": "1"}]},
        {"names": [], "pins": [{"reference": "U2", "pin": "3"}]},
        {"names": [], "pins": [{"reference": "U2", "pin": "4"}]},
    ]
    _populate_nets(circuit, groups, {})
    assert {"VCC", "~N1", "~N2"} == set(circuit.nets)
    assert frozenset({("U1", "1"), ("R1", "2"), ("R2", "1")}) == circuit.nets["VCC"].connections
    assert 3.3 == circuit.nets["VCC"].voltage
    assert "Power" == circuit.nets["VCC"].net_class
    assert True is circuit.nets["VCC"].is_power
    assert frozenset({("U2", "3")}) == circuit.nets["~N1"].connections
    assert frozenset({("U2", "4")}) == circuit.nets["~N2"].connections
    assert False is circuit.nets["~N2"].is_power


def test_populate_nets_detects_power_symbols_and_handles_empty_groups() -> None:
    circuit = IRCircuit()
    groups = [
        {"names": ["CUSTOM_RAIL"], "pins": []},
        {"names": ["SIG"], "pins": [{"reference": "J1", "pin": "1"}]},
        {"names": [], "pins": []},
    ]
    _populate_nets(circuit, groups, {"power_symbols": [{"value": "CUSTOM_RAIL"}]})
    assert True is circuit.nets["CUSTOM_RAIL"].is_power
    assert 0.0 == circuit.nets["CUSTOM_RAIL"].voltage
    assert frozenset() == circuit.nets["CUSTOM_RAIL"].connections
    assert False is circuit.nets["SIG"].is_power
    assert "~N1" in circuit.nets


def test_store_ir_net_group_new_signal_and_existing_power_state() -> None:
    circuit = IRCircuit()
    _store_ir_net_group(circuit, "SIG", {("J1", "2")}, False)
    assert IRNet(name="SIG", connections=frozenset({("J1", "2")})) == circuit.nets["SIG"]
    _store_ir_net_group(circuit, "SIG", {("J2", "3")}, True)
    assert frozenset({("J1", "2"), ("J2", "3")}) == circuit.nets["SIG"].connections
    assert True is circuit.nets["SIG"].is_power
    assert None is circuit.nets["SIG"].voltage
