"""Pinned KiCad 10 canary installer: static supply-chain and workflow contracts."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/ci/install_kicad_10_0_6_appimage.sh"
WORKFLOWS = (
    ("kicad-live-e2e.yml", "Install KiCad 10.0.x CLI"),
    ("dev-bootstrap.yml", "Install KiCad 10.0.6 CLI"),
)


def test_workflows_use_the_same_pinned_installer() -> None:
    for name, step_name in WORKFLOWS:
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        steps = [
            step
            for job in workflow["jobs"].values()
            for step in job.get("steps", [])
            if step.get("name") == step_name
        ]
        assert len(steps) == 1
        assert steps[0]["run"] == "bash scripts/ci/install_kicad_10_0_6_appimage.sh"
        assert "sudo" not in steps[0]["run"]


def test_installer_only_changes_trigger_both_canary_workflows() -> None:
    for name, _ in WORKFLOWS:
        workflow = yaml.safe_load((ROOT / ".github/workflows" / name).read_text())
        triggers = workflow.get("on", workflow.get(True))
        for event in ("pull_request", "push"):
            assert "scripts/ci/install_kicad_10_0_6_appimage.sh" in triggers[event]["paths"]


def test_download_archive_and_executable_have_independent_pinned_sha256() -> None:
    source = SCRIPT.read_text()
    hashes = dict(re.findall(r"readonly (archive_sha256|appimage_sha256)='([a-f0-9]{64})'", source))
    assert set(hashes) == {"archive_sha256", "appimage_sha256"}
    assert hashes["archive_sha256"] != hashes["appimage_sha256"]
    assert source.count("sha256sum --check --status") == 3
    assert "base_url='https://mirrors.mit.edu/kicad/appimage/stable'" in source
    assert "--proto '=https'" in source


def test_member_validation_precedes_extraction_and_runtime_execution() -> None:
    source = SCRIPT.read_text()
    member_check = source.index('"$(tar -tf "$archive")" != "$appimage_name"')
    extraction = source.index("tar --no-same-owner --no-same-permissions -xf")
    archive_hash = source.index('"$archive_sha256" "$archive" | sha256sum')
    executable_hash = source.index('"$appimage_sha256" "$appimage" | sha256sum')
    runtime = source.index('"$appimage" --appimage-extract')
    assert archive_hash < member_check < extraction < executable_hash < runtime


def test_version_and_native_footprint_assets_are_checked_before_ci_export() -> None:
    source = SCRIPT.read_text()
    assert "\"$($cli version)\" != '10.0.6'" in source
    assert "Device.kicad_symdir" in source
    assert "Resistor_SMD.pretty" in source
    assert source.index('"$($cli version)"') < source.index('>> "$GITHUB_PATH"')
    assert "KICAD_CANARY_KICAD_CLI" in source
    assert "KICAD_SYMBOL_DIR" in source
    assert "KICAD10_SYMBOL_DIR" in source
    assert "KICAD_MCP_SYMBOL_LIBRARY_DIR" in source


def test_exact_kicad_10_0_6_symbol_commit_and_official_packer_are_required() -> None:
    source = SCRIPT.read_text()
    assert "7800d91437ce44e2ed0928f2ad31a287457b8a68" in source
    assert "f7384548a683c34076d82469c56bb0eb0ffdb7c50774d87af8463fddb80e152e" in source
    assert "https://gitlab.com/kicad/libraries/kicad-symbols/-/archive/" in source
    assert "--target pack_symbols" in source
    assert "-DKICAD_PACK_SYM_LIBRARIES=ON" in source
    assert source.index('"$symbols_archive_sha256"') < source.index(
        "tar --no-same-owner --no-same-permissions -xzf"
    )
    assert source.index("--target pack_symbols") < source.index("KICAD_SYMBOL_DIR=%s")
