"""Capability-parity matrix invariants (work order P0-T4).

Guards against the cardinal sin of a parity matrix: *false-positive coverage*.
Every tool the matrix names must really be registered, status/channel values must
be in vocabulary, the coverage math must be self-consistent, and the embedded copy
plus generated docs must be in sync with the YAML source of truth.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

import scripts.build_parity_matrix as builder
from kicad_mcp.parity import CHANNELS, STATUSES, coverage_summary, get_matrix

REQUIRED_FIELDS = {
    "capability",
    "kicad_channel",
    "mcp_tool",
    "status",
    "kicad_version_introduced",
    "notes",
}


@pytest.fixture(scope="module")
def matrix() -> dict[str, Any]:
    return get_matrix()


def _rows(matrix: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    for domain, info in matrix["domains"].items():
        for cap in info["capabilities"]:
            yield domain, cap


def test_rows_have_required_fields(matrix: dict[str, Any]) -> None:
    for domain, cap in _rows(matrix):
        missing = REQUIRED_FIELDS - set(cap)
        assert not missing, f"{domain}/{cap.get('capability')} missing fields {missing}"


def test_status_and_channel_vocabulary(matrix: dict[str, Any]) -> None:
    for domain, cap in _rows(matrix):
        assert cap["status"] in STATUSES, f"{domain}: invalid status {cap['status']!r}"
        assert cap["kicad_channel"] in CHANNELS, (
            f"{domain}: invalid channel {cap['kicad_channel']!r}"
        )


def test_no_false_positive_coverage(
    matrix: dict[str, Any], registered_tool_names: set[str]
) -> None:
    for domain, cap in _rows(matrix):
        tool = cap["mcp_tool"]
        if tool is not None:
            assert tool in registered_tool_names, (
                f"{domain}/{cap['capability']}: references unregistered tool '{tool}'"
            )


def test_status_tool_invariants(matrix: dict[str, Any], registered_tool_names: set[str]) -> None:
    for domain, cap in _rows(matrix):
        status, tool, channel = cap["status"], cap["mcp_tool"], cap["kicad_channel"]
        label = f"{domain}/{cap['capability']}"
        if status == "covered":
            assert tool is not None, f"{label}: 'covered' requires a registered tool"
            assert tool in registered_tool_names, f"{label}: 'covered' requires a registered tool"
        if status == "gap":
            assert tool is None, f"{label}: 'gap' must have no tool"
        if status == "gui-only-no-api":
            assert tool is None, (
                f"{label}: 'gui-only-no-api' must be tool-less and channel 'gui-only'"
            )
            assert channel == "gui-only", (
                f"{label}: 'gui-only-no-api' must be tool-less and channel 'gui-only'"
            )


def test_coverage_math(matrix: dict[str, Any]) -> None:
    summary = coverage_summary(matrix)
    for name, stats in summary["domains"].items():
        assert stats["denominator"] == stats["total"] - stats["gui_only_no_api"], name
        if stats["denominator"]:
            expected = round(100.0 * stats["covered"] / stats["denominator"], 1)
            assert stats["coverage_pct"] == expected, name
    overall = summary["overall"]
    assert overall["total"] == sum(s["total"] for s in summary["domains"].values())
    assert 0.0 <= overall["coverage_pct"] <= 100.0


def test_embedded_matrix_matches_yaml() -> None:
    assert get_matrix() == builder.load_matrix(), (
        "Embedded parity_matrix_data.py is stale; run scripts/build_parity_matrix.py"
    )


def test_generated_artifacts_not_drifted() -> None:
    # --check now also guards the README coverage badge against drift.
    assert builder.main(["--check"]) == 0, "Run: uv run python scripts/build_parity_matrix.py"


def test_coverage_meets_committed_baseline(matrix: dict[str, Any]) -> None:
    # P5-T6 regression gate: live coverage must not drop below the committed
    # floor. A KiCad update that breaks a hook (covered -> gap) trips this.
    assert builder.BASELINE_PATH.is_file(), (
        "Missing parity baseline; run: "
        "uv run python scripts/build_parity_matrix.py --update-baseline"
    )
    failures = builder.check_regression(matrix)
    assert not failures, "Capability-parity coverage regressed:\n" + "\n".join(failures)


def test_baseline_not_below_floor_is_a_real_check() -> None:
    # Guard the guard: a fabricated drop below the baseline must be detected,
    # so the gate cannot silently pass on a genuine regression.
    matrix = get_matrix()
    analysis = matrix["domains"]["analysis"]["capabilities"]
    downgraded = next(cap for cap in analysis if cap["status"] == "covered")
    downgraded["status"] = "gap"
    downgraded["mcp_tool"] = None
    failures = builder.check_regression(matrix)
    assert any("analysis" in failure or "overall" in failure for failure in failures)


def test_capability_parity_tool_registered(registered_tool_names: set[str]) -> None:
    assert "kicad_capability_parity" in registered_tool_names
