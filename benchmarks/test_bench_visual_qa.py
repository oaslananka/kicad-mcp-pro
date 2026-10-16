"""Benchmarks for the headless schematic visual-QA engine."""

from __future__ import annotations

import pytest

from kicad_mcp.models import visual_qa
from tests.synthetic import generate_resistor_grid

SIZES = [50, 200]


@pytest.fixture(scope="module", params=SIZES, ids=lambda n: f"{n}_components")
def schematic_text(request: pytest.FixtureRequest) -> str:
    return generate_resistor_grid(request.param)


def test_parse_symbols(benchmark, schematic_text: str) -> None:
    symbols = benchmark(visual_qa.parse_symbols, schematic_text)
    assert symbols


def test_parse_placed_symbols(benchmark, schematic_text: str) -> None:
    placed = benchmark(visual_qa.parse_placed_symbols, schematic_text)
    assert placed


def test_parse_labels(benchmark, schematic_text: str) -> None:
    labels = benchmark(visual_qa.parse_labels, schematic_text)
    assert labels


def test_run_visual_qa(benchmark, schematic_text: str) -> None:
    report = benchmark(visual_qa.run_visual_qa, schematic_text)
    assert report["status"] == "PASS"


def test_run_cosmetic_qa(benchmark, schematic_text: str) -> None:
    report = benchmark(visual_qa.run_cosmetic_qa, schematic_text)
    assert report
