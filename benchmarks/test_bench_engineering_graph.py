"""Benchmarks for the circuit IR, engineering graph, diff, and lint engines."""

from __future__ import annotations

from dataclasses import replace

import pytest

from kicad_mcp.ir import IRCircuit, IRComponent, IRNet, IRPin
from kicad_mcp.ir.diff import circuit_diff
from kicad_mcp.ir.engineering_graph import engineering_graph_diff
from kicad_mcp.ir.engineering_graph_from_ir import graph_from_circuit, update_graph_from_circuit
from kicad_mcp.ir.lint import lint_circuit

PROJECT_KEY = "codspeed-benchmark"


def _build_circuit(n_components: int) -> IRCircuit:
    """Return a resistor chain: each resistor connects net N<i> to net N<i+1>."""
    circuit = IRCircuit(title=PROJECT_KEY)
    for index in range(n_components):
        reference = f"R{index + 1}"
        circuit.components[reference] = IRComponent(
            reference,
            "Device:R",
            "10k",
            "Resistor_SMD:R_0603_1608Metric",
            pins=(IRPin("1", "~"), IRPin("2", "~")),
        )
    for index in range(n_components + 1):
        connections: set[tuple[str, str]] = set()
        if index > 0:
            connections.add((f"R{index}", "2"))
        if index < n_components:
            connections.add((f"R{index + 1}", "1"))
        name = f"N{index}"
        circuit.nets[name] = IRNet(name, frozenset(connections))
    return circuit


@pytest.fixture(scope="module")
def circuits() -> tuple[IRCircuit, IRCircuit]:
    before = _build_circuit(300)
    after = IRCircuit(
        title=before.title,
        components=dict(before.components),
        nets=dict(before.nets),
    )
    after.components["R150"] = replace(after.components["R150"], value="22k")
    return before, after


def test_graph_from_circuit(benchmark, circuits: tuple[IRCircuit, IRCircuit]) -> None:
    before, _after = circuits
    graph = benchmark(graph_from_circuit, before, project_key=PROJECT_KEY)
    assert graph.entities


def test_update_graph_incremental(benchmark, circuits: tuple[IRCircuit, IRCircuit]) -> None:
    before, after = circuits

    def setup() -> tuple[tuple[object, IRCircuit, IRCircuit], dict[str, object]]:
        return (graph_from_circuit(before, project_key=PROJECT_KEY), before, after), {}

    result = benchmark.pedantic(update_graph_from_circuit, setup=setup)
    assert result.work_units == 1


def test_engineering_graph_diff(benchmark, circuits: tuple[IRCircuit, IRCircuit]) -> None:
    before, after = circuits
    old = graph_from_circuit(before, project_key=PROJECT_KEY)
    new = graph_from_circuit(after, project_key=PROJECT_KEY)
    changes = benchmark(engineering_graph_diff, old, new)
    assert changes


def test_circuit_diff(benchmark, circuits: tuple[IRCircuit, IRCircuit]) -> None:
    before, after = circuits
    changes = benchmark(circuit_diff, before, after)
    assert changes


def test_lint_circuit(benchmark, circuits: tuple[IRCircuit, IRCircuit]) -> None:
    before, _after = circuits
    benchmark(lint_circuit, before)
