"""Manufacturing sign-off report builder (work order P5-T3)."""

from __future__ import annotations

from kicad_mcp.project.release_evidence_policy import (
    ContractReleaseEvidenceResult,
    ContractReleaseEvidenceState,
    ReleaseEvidenceGateResult,
)
from kicad_mcp.project.release_evidence_store import ProjectReleaseEvidenceResolution
from kicad_mcp.tools.gates import GateOutcome
from kicad_mcp.tools.signoff import build_signoff_report, render_signoff_report

_PROVENANCE = {
    "kicad_mcp_version": "9.9.9",
    "kicad_cli_version": "10.0.1",
    "rule_profile": "full/manufacturing",
    "intent_hash": "deadbeef",
}

_INTENT = {
    "critical_nets": ["USB_DP", "USB_DM"],
    "power_rails": [{"name": "+3V3"}],
    "thermal_hotspots": ["U1"],
    "manufacturer": "JLCPCB",
    "manufacturer_tier": "standard",
}


def _passing_gates() -> list[GateOutcome]:
    return [
        GateOutcome(name="Schematic", status="PASS", summary="ERC clean"),
        GateOutcome(name="PCB", status="PASS", summary="DRC clean"),
        GateOutcome(name="Manufacturing", status="PASS", summary="DFM clean"),
    ]


def test_signoff_passes_and_binds_every_requirement_to_a_check() -> None:
    report = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE)
    assert report["verdict"] == "PASS"
    assert report["requirements"], "requirements must be derived from intent"
    # Every requirement is bound to at least one passing check.
    for req in report["requirements"]:
        assert req["bound_checks"], f"{req['requirement']} not bound to a check"
        assert req["status"] == "PASS"
    # Provenance is carried through.
    assert report["provenance"]["intent_hash"] == "deadbeef"


def test_signoff_fails_when_a_backing_gate_fails() -> None:
    gates = _passing_gates()
    gates[1] = GateOutcome(name="PCB", status="FAIL", summary="DRC violations")
    report = build_signoff_report(_INTENT, gates, _PROVENANCE)
    assert report["verdict"] == "FAIL"


def test_signoff_unverified_without_declared_intent() -> None:
    report = build_signoff_report({}, _passing_gates(), _PROVENANCE)
    assert report["verdict"] == "UNVERIFIED"
    assert report["requirements"] == []
    assert "nothing to sign off" in report["summary"].lower()


def test_signoff_content_hash_is_deterministic() -> None:
    a = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE)
    b = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE)
    assert a["content_hash"] == b["content_hash"]
    # A material change (a failing gate) changes the hash.
    gates = _passing_gates()
    gates[0] = GateOutcome(name="Schematic", status="FAIL", summary="ERC errors")
    assert build_signoff_report(_INTENT, gates, _PROVENANCE)["content_hash"] != a["content_hash"]


def test_render_signoff_is_human_readable() -> None:
    text = render_signoff_report(build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE))
    assert "Manufacturing sign-off: PASS" in text
    assert "Provenance:" in text
    assert "content hash:" in text


def test_release_blocking_evidence_forces_signoff_fail() -> None:
    blocked = ProjectReleaseEvidenceResolution(
        adopted=True,
        gate=ReleaseEvidenceGateResult(
            approved=False,
            contracts=(
                ContractReleaseEvidenceResult(
                    contract_id="INTENT-USB-SI",
                    contract_version=1,
                    state=ContractReleaseEvidenceState.BLOCKED,
                    reason_codes=("required_evidence_requires_recheck",),
                ),
            ),
        ),
    )
    report = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE, blocked)
    assert report["verdict"] == "FAIL"
    assert report["release_evidence"]["approved"] is False
    assert "release-blocking" in report["summary"]


def test_legacy_signoff_shape_unchanged_without_adopted_contracts() -> None:
    report = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE)
    assert report["verdict"] == "PASS"
    assert "release_evidence" not in report


def test_release_blocker_preserves_existing_gate_failure_summary() -> None:
    gates = _passing_gates()
    gates[1] = GateOutcome(name="PCB", status="FAIL", summary="DRC violations")
    blocked = ProjectReleaseEvidenceResolution(
        adopted=True,
        gate=ReleaseEvidenceGateResult(
            approved=False,
            contracts=(
                ContractReleaseEvidenceResult(
                    contract_id="INTENT-USB-SI",
                    contract_version=1,
                    state=ContractReleaseEvidenceState.BLOCKED,
                    reason_codes=("required_evidence_requires_recheck",),
                ),
            ),
        ),
    )

    report = build_signoff_report(_INTENT, gates, _PROVENANCE, blocked)

    assert report["verdict"] == "FAIL"
    assert "backing gates are not passing" in report["summary"]
    assert "release-blocking HardwareIntentContract evidence" in report["summary"]


def test_reviewed_waiver_downgrades_passing_signoff_to_warn() -> None:
    waived = ProjectReleaseEvidenceResolution(
        adopted=True,
        gate=ReleaseEvidenceGateResult(
            approved=True,
            contracts=(
                ContractReleaseEvidenceResult(
                    contract_id="INTENT-USB-SI",
                    contract_version=1,
                    state=ContractReleaseEvidenceState.WAIVED,
                    evidence_ids=("WAIVER-EVID-1",),
                    reason_codes=("explicit_reviewed_waiver",),
                ),
            ),
        ),
    )

    report = build_signoff_report(_INTENT, _passing_gates(), _PROVENANCE, waived)

    assert report["verdict"] == "WARN"
    assert report["release_evidence"]["approved"] is True
    assert report["release_evidence"]["contracts"][0]["state"] == "waived"
    assert "explicit reviewed contract waiver" in report["summary"]
