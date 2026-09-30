"""Manufacturing sign-off report (work order P5-T3).

Binds each declared design-intent requirement to the gate check(s) that would
catch a violation, attaches the gate evidence and full provenance, and reduces it
to a single PASS/FAIL verdict. Pure and KiCad-free so it is unit-testable; the
live ``project_signoff_report`` tool in :mod:`validation` supplies the gathered
gate outcomes, intent, and provenance.

Honesty: a sign-off is only a PASS when design intent was actually declared and
every gate that backs a requirement passes. A board with no declared intent is
``UNVERIFIED`` — there is nothing to sign off against — not a silent PASS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from ..project.release_evidence_store import ProjectReleaseEvidenceResolution
from .gates import GateOutcome, _combined_status

SignoffVerdict = Literal["PASS", "FAIL", "BLOCKED", "EMPTY", "UNVERIFIED", "WARN"]


@dataclass(slots=True)
class SignoffRequirement:
    """One declared requirement bound to the checks that back it."""

    requirement: str
    category: str
    bound_checks: list[str]
    status: str
    evidence: str


def _requirement_specs(intent: dict[str, Any]) -> list[tuple[str, str, set[str]]]:
    """Derive (requirement, category, gate-name keywords) rows from design intent."""
    specs: list[tuple[str, str, set[str]]] = []
    nets = intent.get("critical_nets") or []
    if nets:
        shown = ", ".join(str(net) for net in nets[:6])
        specs.append(
            (
                f"Critical-net integrity ({len(nets)}): {shown}",
                "signal_integrity",
                {"schematic", "connectivity", "pcb"},
            )
        )
    interfaces = intent.get("interfaces") or []
    if interfaces:
        specs.append(
            (
                f"High-speed interfaces honored ({len(interfaces)})",
                "signal_integrity",
                {"pcb", "connectivity"},
            )
        )
    rails = intent.get("power_rails") or []
    power_refs = intent.get("power_tree_refs") or []
    if rails or power_refs:
        specs.append(
            (
                f"Power delivery ({len(rails)} rail(s), {len(power_refs)} ref(s))",
                "power",
                {"schematic", "pcb"},
            )
        )
    hotspots = intent.get("thermal_hotspots") or []
    if hotspots:
        specs.append(
            (f"Thermal hotspots managed ({len(hotspots)})", "thermal", {"pcb", "manufacturing"})
        )
    compliance = intent.get("compliance") or []
    if compliance:
        specs.append(
            (f"Compliance targets ({len(compliance)})", "compliance", {"manufacturing", "pcb"})
        )
    manufacturer = str(intent.get("manufacturer") or "").strip()
    if manufacturer:
        tier = str(intent.get("manufacturer_tier") or "").strip()
        specs.append(
            (
                f"Manufacturable at {manufacturer} {tier}".strip(),
                "manufacturing",
                {"manufacturing", "footprint", "pcb"},
            )
        )
    return specs


def _bind(keywords: set[str], outcomes: list[GateOutcome]) -> list[GateOutcome]:
    """Return the gates whose name matches a keyword, else all gates (never orphan)."""
    bound = [o for o in outcomes if any(k in o.name.casefold() for k in keywords)]
    return bound or list(outcomes)


def _apply_release_evidence(
    verdict: SignoffVerdict,
    summary: str,
    release_evidence: ProjectReleaseEvidenceResolution | None,
) -> tuple[SignoffVerdict, str, dict[str, Any] | None]:
    if release_evidence is None or not release_evidence.adopted:
        return verdict, summary, None

    contracts = (
        [
            {
                "contract_id": result.contract_id,
                "contract_version": result.contract_version,
                "state": result.state.value,
                "evidence_ids": list(result.evidence_ids),
                "reason_codes": list(result.reason_codes),
            }
            for result in release_evidence.gate.contracts
        ]
        if release_evidence.gate is not None
        else []
    )
    payload: dict[str, Any] = {
        "approved": release_evidence.approved,
        "errors": list(release_evidence.errors),
        "contracts": contracts,
    }

    if not release_evidence.approved:
        release_blocker = (
            "Sign-off blocked: release-blocking HardwareIntentContract evidence "
            "is missing, stale, invalidated, or unresolved."
        )
        combined_summary = release_blocker if verdict == "PASS" else f"{summary} {release_blocker}"
        return "FAIL", combined_summary, payload

    if release_evidence.gate is not None and release_evidence.gate.waived and verdict == "PASS":
        return "WARN", "Sign-off requires explicit reviewed contract waiver evidence.", payload

    return verdict, summary, payload


def build_signoff_report(
    intent: dict[str, Any],
    outcomes: list[GateOutcome],
    provenance: dict[str, Any],
    release_evidence: ProjectReleaseEvidenceResolution | None = None,
) -> dict[str, Any]:
    """Build the structured sign-off report. Deterministic: no timestamps inside."""
    gate_status = _combined_status(outcomes) if outcomes else "EMPTY"
    specs = _requirement_specs(intent)

    requirements: list[SignoffRequirement] = []
    for text, category, keywords in specs:
        bound = _bind(keywords, outcomes)
        status = _combined_status(bound) if bound else "UNVERIFIED"
        evidence = "; ".join(f"{o.name}: {o.status}" for o in bound) or "no covering check"
        requirements.append(
            SignoffRequirement(text, category, [o.name for o in bound], status, evidence)
        )

    if not specs:
        verdict: SignoffVerdict = "UNVERIFIED"
        summary = (
            "No design intent declared — nothing to sign off against. Declare "
            "requirements with project_set_design_intent() first."
        )
    elif gate_status == "WARN":
        verdict = "WARN"
        summary = (
            "Sign-off passed with advisories: one or more backing gates reported "
            "WARN. Review the warned checks before release."
        )
    elif gate_status != "PASS":
        verdict = gate_status
        summary = "Sign-off blocked: one or more backing gates are not passing."
    else:
        verdict = "PASS"
        summary = f"All {len(specs)} declared requirement(s) bound to passing checks."

    verdict, summary, release_payload = _apply_release_evidence(
        verdict,
        summary,
        release_evidence,
    )

    checks = [
        {"name": o.name, "status": o.status, "summary": o.summary, "evidence": list(o.details)}
        for o in outcomes
    ]
    body: dict[str, Any] = {
        "verdict": verdict,
        "summary": summary,
        "requirements": [asdict(req) for req in requirements],
        "checks": checks,
        "provenance": provenance,
    }
    if release_payload is not None:
        body["release_evidence"] = release_payload
    body["content_hash"] = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    return body


def render_signoff_report(report: dict[str, Any]) -> str:
    """Render the structured sign-off report as a human-readable text block."""
    lines = [
        f"Manufacturing sign-off: {report['verdict']}",
        f"- {report['summary']}",
        "",
        "Requirements:",
    ]
    requirements = report["requirements"]
    if requirements:
        for req in requirements:
            lines.append(f"  [{req['status']}] {req['requirement']}")
            lines.append(f"      backed by: {req['evidence']}")
    else:
        lines.append("  (none declared)")
    lines.extend(["", "Checks:"])
    for check in report["checks"]:
        lines.append(f"  [{check['status']}] {check['name']} — {check['summary']}")
    release_evidence = report.get("release_evidence")
    if release_evidence is not None:
        lines.extend(["", "Release contract evidence:"])
        lines.append(f"  approved: {release_evidence['approved']}")
        for contract in release_evidence["contracts"]:
            lines.append(
                "  "
                + f"[{contract['state']}] {contract['contract_id']}@{contract['contract_version']}"
            )
            if contract["reason_codes"]:
                lines.append("      reasons: " + ", ".join(contract["reason_codes"]))
        for error in release_evidence["errors"]:
            lines.append(f"  ERROR: {error}")
    prov = report["provenance"]
    lines.extend(
        [
            "",
            "Provenance:",
            f"  kicad-mcp-pro: {prov.get('kicad_mcp_version', 'unknown')}",
            f"  kicad-cli: {prov.get('kicad_cli_version', 'unknown')}",
            f"  rule profile: {prov.get('rule_profile', 'unknown')}",
            f"  intent hash: {prov.get('intent_hash', 'none')}",
            f"  content hash: {report['content_hash']}",
        ]
    )
    return "\n".join(lines)
