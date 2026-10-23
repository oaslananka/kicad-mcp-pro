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


def test_107_installer_pins_official_archive_and_appimage_hashes() -> None:
    source = INSTALLER.read_text()
    assert "3c6067b03e2e6eb7b3e17f63f6d57c2937a19c39d585edd0c0a8d0bebaec8969" in source
    assert "05855274adb8eb7164ab886cfbbe8da7dd84f961d6d04783b66ffcb5011287cd" in source
    assert "https://mirrors.mit.edu/kicad/appimage/stable" in source
    assert "kicad-10.0.7-x86_64-lite.AppImage.tar" in source
    assert source.count("sha256sum --check --status") == 3
    assert source.index('"$archive_sha256"') < source.index("tar --no-same-owner")
    assert source.index('"$appimage_sha256"') < source.index("--appimage-extract")
    assert "Bundled KiCad CLI version is not exactly 10.0.7." in source


def test_107_installer_uses_version_matched_official_symbol_packer() -> None:
    source = INSTALLER.read_text()
    assert "1b2b42d49bc41559e43f590b084e7fe8f1e7f5fc" in source
    assert "2c6c52d300ac8f0ddaf750b301e2ad0396946b2b3417c01114a5be26e77bc3df" in source
    assert "gitlab.com/kicad/libraries/kicad-symbols/-/archive/" in source
    assert "-DKICAD_PACK_SYM_LIBRARIES=ON" in source
    assert "--target pack_symbols" in source
    assert "KICAD_MCP_SYMBOL_LIBRARY_DIR" in source
    assert "KICAD_SYMBOL_DIR" in source
    assert "KICAD_CANARY_KICAD_CLI" in source
    assert source.index('"$symbols_archive_sha256"') < source.index(
        "tar --no-same-owner --no-same-permissions -xzf"
    )


def test_primary_gate_does_not_change_historical_compatibility_evidence() -> None:
    # The global patch baseline is promoted, but the Jammy 10.0.6 lane remains pinned.
    matrix = yaml.safe_load((ROOT / "compatibility.yaml").read_text())
    assert matrix["kicad"]["latestVerified"] == "10.0.7"
    assert matrix["kicad10FeatureParity"]["baseline"] == "10.0.7"
    assert matrix["kicad10FeatureParity"]["candidatePatchReview"]["version"] == "10.0.7"
