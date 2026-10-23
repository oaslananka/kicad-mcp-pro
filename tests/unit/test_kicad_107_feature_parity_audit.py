"""KiCad 10.0.7 patch review must not promote unproven parity or Jammy."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
AUDIT = ROOT / "docs/evidence/kicad-10-0-7/2026-10-12-feature-parity-audit.md"
EXPECTED_GAPS = {
    "erc-json-unit-scale",
    "multi-root-schematic-plot",
    "bom-project-output-filename",
    "gerber-drill-marks",
    "allegro-24-25-cli-capability",
    "ipc-expanded-object-contracts",
}


def _matrix() -> dict:
    return yaml.safe_load((ROOT / "compatibility.yaml").read_text(encoding="utf-8"))


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text(encoding="utf-8"))


def test_107_promoted_scope_keeps_unpublished_features_blocked() -> None:
    matrix = _matrix()
    parity = matrix["kicad10FeatureParity"]
    review = parity["candidatePatchReview"]
    assert matrix["kicad"]["latestVerified"] == parity["baseline"] == "10.0.7"
    assert parity["documentation"] == "docs/compatibility/kicad-10-0-7-feature-parity.md"
    assert parity["sources"]["releaseNotes"].endswith("/2026/10/KiCad-10.0.7-Release/")
    assert parity["sources"]["releaseTag"].endswith("/releases/tag/10.0.7")
    assert review["version"] == "10.0.7"
    assert review["status"] == "reviewed-with-blocked-optional-capabilities"
    assert review["globalPromotionApproved"] is True
    assert review["issue"] == "https://github.com/oaslananka/kicad-mcp-pro/issues/1181"
    assert review["audit"] == AUDIT.relative_to(ROOT).as_posix()
    assert AUDIT.is_file()
    assert review["upstreamReleaseNotes"].endswith("KiCad-10.0.7-Release/")
    assert len(review["targetedRegressionGaps"]) == len(EXPECTED_GAPS)
    assert set(review["targetedRegressionGaps"]) == EXPECTED_GAPS
    assert parity["surfaces"]["importers"]["allegro"]["status"] == "blocked"
    expanded = parity["surfaces"]["ipc"]["ipc_107_expanded_objects"]
    assert expanded["status"] == "blocked"
    assert "path:scripts/kicad_107_ipc_binding_gate.py" in expanded["evidence"]
    evidence = review["qualificationEvidence"]
    assert evidence["expandedIpcWrappers"].startswith("blocked-")
    assert evidence["allegroCliImporter"].startswith("blocked-")
    assert evidence["windowsGuiRun"].endswith("/39960284615")
    assert evidence["macosGuiRun"].endswith("/39960288521")
    assert evidence["chocolateyPackage"].endswith("/10.0.7")
    assert evidence["officialWindowsInstallerSha256"] == (
        "ce3881b6a9188eb34ac1ebaaec7651149e8a025206410addfb11a1a9656ecf95"
    )


def test_audit_accounts_for_every_targeted_upstream_gap_without_claiming_pass() -> None:
    review = _matrix()["kicad10FeatureParity"]["candidatePatchReview"]
    audit = AUDIT.read_text(encoding="utf-8")
    for gap in review["targetedRegressionGaps"]:
        assert audit.count(f"`{gap}`") == 1
    assert "targeted-evidence-pending" in audit
    assert "scripts/kicad_107_erc_units.py" in audit
    assert "scripts/kicad_107_flat_root_pdf.py" in audit
    assert "scripts/kicad_107_gerber_drill_marks.py" in audit
    assert "tests/gui/manual_kicad_107_bom_gui.sh" in audit
    assert "scripts/kicad_107_bom_portable.py" in audit
    assert "scripts/kicad_107_ipc_binding_gate.py" in audit
    assert "10.0.6" in audit
    assert "10.0.7" in audit
    assert "#25582" in audit
    assert "#24860" in audit
    assert "#25532" in audit
    assert "#729" in audit
    assert "#730" in audit
    assert "not** a new required PR gate" in audit
    assert "manual" in audit
    assert "Do **not**" in audit


def test_both_jammy_legacy_jobs_explicitly_fail_on_version_drift() -> None:
    review = _matrix()["kicad10FeatureParity"]["candidatePatchReview"]
    legacy = review["ubuntu22Legacy"]
    assert legacy["runner"] == "ubuntu-22.04"
    assert legacy["retainedVersion"] == "10.0.6"
    assert set(legacy["workflows"]) == {
        ".github/workflows/kicad-live-e2e.yml",
        ".github/workflows/dev-bootstrap.yml",
    }
    assert "libgit2" in legacy["reason"]
    for name, job_name in (
        ("kicad-live-e2e.yml", "kicad-10-0-6-canary"),
        ("dev-bootstrap.yml", "kicad-canary"),
    ):
        job = _workflow(name)["jobs"][job_name]
        assert job["runs-on"] == "ubuntu-22.04"
        installer_step = next(
            step for step in job["steps"] if step.get("name", "").startswith("Install KiCad 10")
        )
        assert installer_step["run"] == "bash scripts/ci/install_kicad_10_0_6_appimage.sh"
        assert job.get("continue-on-error") is not True
    installer = (ROOT / "scripts/ci/install_kicad_10_0_6_appimage.sh").read_text()
    assert "if [[ \"$($cli version)\" != '10.0.6' ]]" in installer
    assert "readonly archive_sha256=" in installer
    assert "readonly appimage_sha256=" in installer
    assert "10.0.7" not in installer


def test_real_automatic_windows_source_is_not_legacy_or_gui_evidence() -> None:
    review = _matrix()["kicad10FeatureParity"]["candidatePatchReview"]
    native = review["windowsNativeAutomatic"]
    assert native["mainRevision"] == "3978af8710ca1b117f0a037f103d873ef5ab6564"
    assert native["run"].endswith("/39900817488")
    assert native["canarySteps"] == 32
    assert native["semanticMatches"] == native["semanticTotal"] == 5
    native_workflow = _workflow("kicad-10-0-7-windows-qualification.yml")
    events = native_workflow.get("on", native_workflow.get(True))
    assert set(events) == {"push", "schedule", "workflow_dispatch"}
    assert events["push"]["branches"] == ["main"]
    assert native_workflow["permissions"] == {"contents": "read"}
    gui = _workflow("kicad-10-0-7-windows-gui-ipc-qualification.yml")
    assert gui.get("on", gui.get(True)) == {"workflow_dispatch": None}


def test_legacy_and_candidate_documentation_are_cross_linked() -> None:
    baseline = (ROOT / "docs/status/kicad-10-0-6-baseline.md").read_text(encoding="utf-8")
    parity_doc = (ROOT / "docs/compatibility/kicad-10-0-6-feature-parity.md").read_text(
        encoding="utf-8"
    )
    name = AUDIT.name
    assert name in baseline
    assert name in parity_doc
    assert "ubuntu-22.04" in baseline
    assert "10.0.6" in baseline
    current = (ROOT / "docs/compatibility/kicad-10-0-7-feature-parity.md").read_text()
    assert "0.9.0" in current
    assert "blocked" in current
    assert "3978af8710ca1b117f0a037f103d873ef5ab6564" in current
    assert "10.0.7" in baseline
