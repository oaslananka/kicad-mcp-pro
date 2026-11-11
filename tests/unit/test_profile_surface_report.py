from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.profile_surface_report as report


@pytest.fixture(scope="module")
def committed_snapshot() -> dict[str, object]:
    return json.loads(report.DEFAULT_OUTPUT.read_text(encoding="utf-8"))


def test_profile_surface_report_matches_committed_snapshot(
    committed_snapshot: dict[str, object],
) -> None:
    assert report.build_report() == committed_snapshot


def test_bounded_surfaces_reduce_catalog_pressure_and_preserve_review_contract(
    committed_snapshot: dict[str, object],
) -> None:
    data = committed_snapshot["profiles"]
    assert isinstance(data, dict)
    default = data["default"]
    review = data["review"]
    build = data["build"]
    expert = data["expert"]
    assert isinstance(default, dict)
    assert isinstance(review, dict)
    assert isinstance(build, dict)
    assert isinstance(expert, dict)

    assert default["callableTools"] == 25
    assert default["forbiddenToolExposures"] == 0
    assert review["profileTaggedCases"] == 8
    assert review["profileTaggedCasesCovered"] == 8
    assert review["profileTaggedCoveragePct"] == 100.0
    assert review["forbiddenToolExposures"] == 0
    assert build["profileTaggedCases"] == 4
    assert build["profileTaggedCasesCovered"] == 4
    assert build["profileTaggedCoveragePct"] == 100.0
    assert expert["goldenToolCallCases"] == 55
    assert expert["goldenCasesCovered"] == 55
    assert expert["goldenCoveragePct"] == 100.0
    assert default["toolReductionVsExpertPct"] >= 90.0
    assert default["catalogReductionVsExpertPct"] >= 90.0
    assert expert["callableTools"] > default["callableTools"]
    assert expert["forbiddenToolExposures"] > default["forbiddenToolExposures"]
    for profile, expected_count in (
        ("default", 25),
        ("review", 25),
        ("build", 24),
        ("release", 24),
    ):
        surface = data[profile]
        assert isinstance(surface, dict)
        assert surface["declaredTools"] == expected_count
        assert surface["callableTools"] == expected_count


def test_profile_surface_report_check_mode_detects_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(report, "build_report", lambda: {"schemaVersion": "test"})
    output = tmp_path / "snapshot.json"
    output.write_text("{}\n", encoding="utf-8")

    assert report.main(["--output", str(output), "--check"]) == 1
    assert report.main(["--output", str(output)]) == 0
    assert report.main(["--output", str(output), "--check"]) == 0
