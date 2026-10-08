"""Pin measured native KiCad benchmark artifacts without overstating their scope."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/native-board-readiness"
MANIFEST = ROOT / "tests/fixtures/native_demo_manifests/jetson-agx-thor-baseboard-kicad10.json"


def test_observed_small_fixtures_are_source_bound_and_not_credited_as_agent_success() -> None:
    report = json.loads((EVIDENCE / "2026-10-08-kicad10-fixture-audit.json").read_text())
    assert report["schema_version"] == "native-fixture-readiness.v0"
    assert report["kicad_cli_version"] == "10.0.6"
    assert report["classification"] == "existing_fixture_readiness_not_agent_outcome"
    assert report["sample_count_per_case"] == 3
    assert len(report["cases"]) == 4
    for case in report["cases"]:
        assert not case["is_autonomous_reference_success"]
        assert not case["qualifies_944_min_1000_components"]
        assert case["native_peak_rss_kib"] is None
        original = ROOT / case["root"]
        for name, digest in case["sources_sha256"].items():
            actual = hashlib.sha256((original / name).read_bytes()).hexdigest()
            assert actual == digest, "native fixture changed; baseline no longer applies"
        assert len(case["drc_observations"]) == 3
        assert all(x["status"] != "clean" for x in case["drc_observations"])
    assert {board["board_id"] for board in report["reference_corpus"]} == {
        "esp32-c6-usbc",
        "stm32f072-usbc",
        "rp2350-usbc",
    }
    assert not any(
        board["autonomous_success_verified_by_this_audit"] for board in report["reference_corpus"]
    )


def test_large_native_demo_report_is_pinned_to_license_and_input_manifest() -> None:
    result = json.loads((EVIDENCE / "2026-10-08-kicad10-jetson-large.json").read_text())
    input_manifest = json.loads(MANIFEST.read_text())
    assert result["schema_version"] == "native-kicad-large-inspect.v0"
    assert result["input_manifest_sha256"] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert result["pcb_sha256"] == input_manifest["files"][input_manifest["pcb"]]
    assert input_manifest["license"] == result["license"] == "Apache-2.0"
    assert result["schematic_source_files"] >= 2
    assert result["run_count"] == len(result["observations"]) == 3
    assert result["status"] == "native_large_project_baseline_only"
    assert all(
        x["footprints"] >= 1000 and x["process_peak_rss_kib"] > 0 for x in result["observations"]
    )
    assert len({x["kicad_build_version"] for x in result["observations"]}) == 1
    assert all(x["load_ms"] >= 0 and x["inspect_ms"] >= 0 for x in result["observations"])
    assert "incremental mutation/update latency" in result["not_measured"]
    assert "agent task-success denominator" in result["not_measured"]
    assert "/home/" not in json.dumps(result)
    assert "/" + "tmp/" not in json.dumps(result)
