"""Primary stable native canary policy without importing or launching KiCad."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts/ci/install_kicad_10_0_7_noble.sh"


def _workflow(name: str) -> dict[object, Any]:
    result = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text())
    assert isinstance(result, dict)
    return result


def test_107_is_primary_pr_native_lane_and_106_remains_nonblocking() -> None:
    workflow = _workflow("kicad-live-e2e.yml")
    events = workflow.get("on", workflow.get(True))
    assert isinstance(events, dict)
    assert "pull_request" in events
    assert "scripts/ci/install_kicad_10_0_7_noble.sh" in events["pull_request"]["paths"]
    primary = workflow["jobs"]["kicad-10-0-7-primary-canary"]
    assert primary["runs-on"] == "ubuntu-24.04"
    assert primary.get("if") is None
    steps = [step.get("run", "") for step in primary["steps"]]
    assert "bash scripts/ci/install_kicad_10_0_7_noble.sh" in steps
    assert any('test "$(kicad-cli version)" = "10.0.7"' in step for step in steps)
    assert any(
        "scripts/kicad_canary.py run" in step and "--kicad-range 10.0.x" in step for step in steps
    )
    assert any(
        "kicad-10-0-7-primary-canary" == step.get("with", {}).get("name")
        for step in primary["steps"]
    )
    legacy = workflow["jobs"]["kicad-10-0-6-canary"]
    assert legacy["runs-on"] == "ubuntu-22.04"
    assert legacy["if"] == "github.event_name != 'pull_request'"
    bootstrap_legacy = _workflow("dev-bootstrap.yml")["jobs"]["kicad-canary"]
    assert bootstrap_legacy["if"] == "github.event_name == 'workflow_dispatch'"


def test_107_install_rejects_version_fallback_for_all_three_apt_packages() -> None:
    source = INSTALLER.read_text()
    assert "ppa:kicad/kicad-10.0-releases" in source
    assert "APT::Update::Error-Mode=any update" in source
    assert "for package in kicad kicad-symbols kicad-footprints; do" in source
    assert '"$candidate" != 10.0.7*' in source
    assert "\"$version\" != '10.0.7'" in source
    assert "Device.kicad_sym" in source and "Resistor_SMD.pretty" in source
    assert "add-apt-repository" in source and "apt-cache policy" in source
    assert source.index("APT::Update::Error-Mode=any update") < source.index("apt-cache policy")
    assert source.index("apt-cache policy") < source.index("install \\\n")


def test_primary_gate_does_not_change_historical_compatibility_evidence() -> None:
    # This MR is a CI priority adjustment, not a fabrication or release gate.
    matrix = yaml.safe_load((ROOT / "compatibility.yaml").read_text())
    assert matrix["kicad"]["latestVerified"] == "10.0.6"
    assert matrix["kicad10FeatureParity"]["baseline"] == "10.0.6"
    assert matrix["kicad10FeatureParity"]["candidatePatchReview"]["version"] == "10.0.7"
