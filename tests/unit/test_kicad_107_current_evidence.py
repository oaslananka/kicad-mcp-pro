"""Bounded, source-linked 10.0.7 verification must not imply global promotion."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "docs/evidence/kicad-10-0-7/2026-10-11-main-qualification.json"
NOTE = ROOT / "docs/evidence/kicad-10-0-7/2026-10-11-main-qualification.md"


def _evidence() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_exact_source_and_safe_support_boundary() -> None:
    report = _evidence()
    assert report["schemaVersion"] == "kicad-107-main-qualification-checkpoint.v1"
    assert report["sourceRevision"] == "ee60c037a25187b6d2487b45d085781c6986f25b"
    assert report["kicadVersion"] == "10.0.7"
    assert report["globalPromotionApproved"] is False
    assert report["latestVerifiedRetained"] == "10.0.6"
    assert report["status"] == "bounded-10.0.7-evidence-not-global-support-promotion"
    assert len(report["outstandingGlobalPromotionGates"]) >= 3


def test_native_gui_and_physical_results_are_not_conflated() -> None:
    report = _evidence()
    for key in ("linuxNative", "windowsNative", "macOsCurrent"):
        native = report[key]
        assert native["canarySteps" if key != "macOsCurrent" else "nativeSteps"] == 32
        assert native["semanticMatches"] == native["semanticTotal"] == 5
    win = report["windowsNative"]
    assert win["failingFixtures"] == 0
    assert win["allowedSkips"] == 2
    assert win["installerSignature"] == "Valid"
    assert len(win["installerSha256"]) == 64
    assert report["windowsGuiIpc"]["actualEditorTests"] == 2
    assert report["windowsGuiIpc"]["failures"] == 0
    mac = report["macOsCurrent"]
    assert (mac["actualEditorTests"], mac["failures"], mac["skips"]) == (2, 0, 0)
    assert mac["signedInstallerVerification"] == "valid"
    physical = report["windowsPhysicalFixtureRegression"]
    assert (physical["fixtureCount"], physical["cliOperations"]) == (6, 19)
    assert (physical["sourceFilesHashed"], physical["sourceMutations"]) == (21, 0)
    assert physical["manufacturingSuccessApproved"] is False
    assert physical["noProviderCalls"] is True
    drc = report["linuxWindowsDiagnosticParity"]
    assert (drc["drcViolationCountBoth"], drc["drcUnconnectedCountBoth"]) == (17, 4)
    assert drc["violationExitCode"] == 5
    assert drc["claimsCleanBoard"] is False


def test_bounded_report_has_no_local_paths_and_keeps_review_links() -> None:
    report = _evidence()
    serialized = json.dumps(report, sort_keys=True)
    assert "C:\\Users" not in serialized
    assert "/home/" not in serialized
    assert "sk-" not in serialized
    note = NOTE.read_text(encoding="utf-8")
    for run_id in (38170396646, 38170399571, 38170872908):
        assert report["sourceRevision"] == "ee60c037a25187b6d2487b45d085781c6986f25b"
        assert str(run_id) in note
    assert "Chocolatey" in note
    assert "Ubuntu 22.04" in note
    assert "latestVerified" in note
    assert "10.0.6" in note
