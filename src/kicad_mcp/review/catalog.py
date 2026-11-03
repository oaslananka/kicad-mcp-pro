"""Pure-domain engineering review rule catalog and context-aware resolver (#1579).

In accordance with milestone M18 principles:
- Rule catalog is versioned, pure-domain, and free of KiCad subprocess dependencies.
- Applicability resolver explicitly reports APPLICABLE, NOT_APPLICABLE, or UNDETERMINED.
- Missing context or conflicting inputs never synthesize a PASS.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..models.review import (
    AssessmentStatus,
    EvaluationMethod,
    ResolvedReviewRule,
    ReviewAssessment,
    ReviewContext,
    ReviewCoverage,
    ReviewDomain,
    ReviewRule,
    RuleApplicability,
)


class ReviewRuleCatalog:
    """Registry of versioned engineering review rules."""

    def __init__(self, rules: Iterable[ReviewRule] | None = None) -> None:
        self._rules_by_key: dict[tuple[str, int], ReviewRule] = {}
        if rules:
            for rule in rules:
                self.register(rule)

    def register(self, rule: ReviewRule) -> None:
        """Register a versioned rule. Rejects duplicate (id, revision) and conflicting revisions."""
        key = (rule.rule_id, rule.revision)
        if key in self._rules_by_key:
            raise ValueError(
                f"Duplicate review rule: '{rule.rule_id}' revision {rule.revision} is registered."
            )
        # Verify that if an existing revision exists, domain and title are consistent
        existing = [r for (rid, _), r in self._rules_by_key.items() if rid == rule.rule_id]
        for past in existing:
            if past.domain != rule.domain:
                raise ValueError(
                    f"Conflicting rule revision for '{rule.rule_id}': domain changed from "
                    f"'{past.domain}' (r{past.revision}) to '{rule.domain}' (r{rule.revision})."
                )
        self._rules_by_key[key] = rule

    def get(self, rule_id: str, revision: int | None = None) -> ReviewRule:
        """Get a rule by ID and optional revision (defaults to highest revision)."""
        matching = [r for (rid, _), r in self._rules_by_key.items() if rid == rule_id]
        if not matching:
            raise KeyError(f"Review rule '{rule_id}' was not found in catalog.")
        if revision is not None:
            for rule in matching:
                if rule.revision == revision:
                    return rule
            raise KeyError(f"Review rule '{rule_id}' revision {revision} was not found.")
        return max(matching, key=lambda r: r.revision)

    def list_rules(self, domain: ReviewDomain | None = None) -> list[ReviewRule]:
        """List registered rules, optionally filtered by domain."""
        rules = list(self._rules_by_key.values())
        if domain is not None:
            rules = [r for r in rules if r.domain == domain]
        return sorted(rules, key=lambda r: (r.domain, r.rule_id, r.revision))

    def resolve(self, context: ReviewContext) -> list[ResolvedReviewRule]:
        """Pure-domain resolution of applicable rules against the provided ReviewContext."""
        resolved: list[ResolvedReviewRule] = []

        context_keys = set(context.explicit_requirements.keys())
        context_keys |= set(context.inferred_values.keys())
        if context.operating_voltage_v is not None:
            context_keys.add("operating_voltage_v")
        if context.operating_current_a is not None:
            context_keys.add("operating_current_a")
        if context.declared_routing_style is not None:
            context_keys.add("declared_routing_style")
        if context.selected_mfg_profile is not None:
            context_keys.add("selected_mfg_profile")
        if context.has_kicad_cli:
            context_keys.add("kicad_cli")
        if context.has_3d_models:
            context_keys.add("3d_models")

        for rule in self.list_rules():
            missing = [inp for inp in rule.required_inputs if inp not in context_keys]

            # Domain-specific applicability logic
            if rule.domain == ReviewDomain.SAFETY and "hazardous" in rule.rule_id:
                if not context.is_hv and "hazardous_mains" not in context.technical_domains:
                    resolved.append(
                        ResolvedReviewRule(
                            rule=rule,
                            status=RuleApplicability.NOT_APPLICABLE,
                            rationale="SELV project; mains insulation rules do not apply.",
                        )
                    )
                    continue
                # Check conflicting HV declarations
                if (
                    context.is_hv
                    and context.operating_voltage_v is not None
                    and context.operating_voltage_v < 50.0
                ):
                    resolved.append(
                        ResolvedReviewRule(
                            rule=rule,
                            status=RuleApplicability.UNDETERMINED,
                            rationale=(
                                f"Conflicting context: is_hv=True but voltage is "
                                f"{context.operating_voltage_v} V (< 50 V SELV threshold)."
                            ),
                            missing_inputs=["voltage_reconciliation"],
                        )
                    )
                    continue

            if rule.domain == ReviewDomain.ROUTING and rule.rule_id == "routing.orthogonal_corners":
                if context.declared_routing_style == "orthogonal_allowed":
                    resolved.append(
                        ResolvedReviewRule(
                            rule=rule,
                            status=RuleApplicability.NOT_APPLICABLE,
                            rationale="Project explicitly declares orthogonal routing is allowed.",
                        )
                    )
                    continue
                if context.declared_routing_style in (
                    "strict_45",
                    "require_chamfer",
                    "chamfer_required",
                ):
                    resolved.append(
                        ResolvedReviewRule(
                            rule=rule,
                            status=RuleApplicability.APPLICABLE,
                            rationale=(
                                f"Enforcing explicit project routing style policy: "
                                f"'{context.declared_routing_style}'."
                            ),
                            applied_threshold=0,
                            threshold_unit="count",
                        )
                    )
                    continue
                if (
                    context.declared_routing_style is None
                    and "high_speed" not in context.technical_domains
                ):
                    resolved.append(
                        ResolvedReviewRule(
                            rule=rule,
                            status=RuleApplicability.APPLICABLE,
                            rationale="Advisory style check: no explicit routing policy declared.",
                            applied_threshold=0,
                            threshold_unit="count",
                        )
                    )
                    continue

            if missing:
                resolved.append(
                    ResolvedReviewRule(
                        rule=rule,
                        status=RuleApplicability.UNDETERMINED,
                        rationale=f"Required inputs missing from context: {', '.join(missing)}.",
                        missing_inputs=missing,
                    )
                )
                continue

            resolved.append(
                ResolvedReviewRule(
                    rule=rule,
                    status=RuleApplicability.APPLICABLE,
                    rationale=f"Applicable for {context.maturity} stage in domain {rule.domain}.",
                    applied_threshold=None,
                    threshold_unit=rule.units,
                )
            )

        return resolved


def compute_coverage(
    resolved_rules: list[ResolvedReviewRule],
    assessments: list[ReviewAssessment],
    justified_exclusions: dict[str, str] | None = None,
) -> ReviewCoverage:
    """Compute exact review coverage metrics without allowing missing checks to become PASS."""
    coverage = ReviewCoverage(
        total_rules=len(resolved_rules),
        justified_exclusions=justified_exclusions or {},
    )

    assessment_by_rule_id = {a.rule_id: a for a in assessments}

    for resolved in resolved_rules:
        if resolved.status == RuleApplicability.APPLICABLE:
            coverage.applicable_count += 1
        elif resolved.status == RuleApplicability.NOT_APPLICABLE:
            coverage.not_applicable_count += 1
        elif resolved.status == RuleApplicability.UNDETERMINED:
            coverage.undetermined_count += 1

        assessment = assessment_by_rule_id.get(resolved.rule.rule_id)
        if resolved.status == RuleApplicability.APPLICABLE:
            is_unassessed_or_blocked = assessment is None or assessment.status in {
                AssessmentStatus.NOT_ASSESSED,
                AssessmentStatus.BLOCKED,
            }
            if assessment is None or assessment.status == AssessmentStatus.NOT_ASSESSED:
                coverage.not_assessed_count += 1
            elif assessment.status == AssessmentStatus.PASS:
                coverage.passed_count += 1
            elif assessment.status == AssessmentStatus.WARN:
                coverage.warned_count += 1
            elif assessment.status == AssessmentStatus.FAIL:
                coverage.failed_count += 1
            elif assessment.status == AssessmentStatus.BLOCKED:
                coverage.blocked_count += 1

            if is_unassessed_or_blocked and resolved.rule.is_mandatory:
                if resolved.rule.rule_id not in coverage.justified_exclusions:
                    coverage.required_unassessed.append(resolved.rule.rule_id)

    return coverage


def build_standard_rule_catalog() -> ReviewRuleCatalog:
    """Instantiate standard reviewed engineering rule catalog."""
    catalog = ReviewRuleCatalog()

    catalog.register(
        ReviewRule(
            rule_id="routing.orthogonal_corners",
            revision=1,
            domain=ReviewDomain.ROUTING,
            title="PCB 90-Degree Route Corner Style",
            source_doc="KiCad MCP Professional Routing Guidelines",
            source_revision="2026.1",
            required_inputs=["tracks"],
            units="count",
            method=EvaluationMethod.HEURISTIC,
            severity="warning",
            rationale="Right-angle track corners should be chamfered for professional aesthetic.",
            remediation="Refactor 90-degree track vertices to 45-degree chamfers.",
            is_mandatory=False,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="placement.decoupling_pin_connectivity",
            revision=1,
            domain=ReviewDomain.PLACEMENT,
            title="Same-Net IC Power Pin Decoupling Placement",
            source_doc="High-Speed Digital Design Best Practices",
            source_revision="2024.1",
            required_inputs=["supply_net", "power_pad_positions"],
            units="mm",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale="Decoupler must share the exact supply net and local ground return.",
            remediation="Connect capacitor to the same rail and place within target distance.",
            is_mandatory=True,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="safety.hazardous_mains_clearance",
            revision=1,
            domain=ReviewDomain.SAFETY,
            title="Hazardous Mains Creepage and Clearance Distance",
            source_doc="IEC 60664-1",
            source_revision="2020-ed3",
            required_inputs=["operating_voltage_v", "pad_spacing_mm"],
            units="mm",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale="Mains and high-voltage rails require certified minimum clearance.",
            remediation="Increase spacing between high-voltage nets and low-voltage copper.",
            is_mandatory=True,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="dfm.circular_pth_annular_ring",
            revision=1,
            domain=ReviewDomain.DFM,
            title="Nominal Circular PTH Annular Ring Minimum",
            source_doc="Manufacturer Capability Specification",
            source_revision="2026.04",
            required_inputs=["selected_mfg_profile", "pth_pads"],
            units="mm",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale="Through-hole annular rings below manufacturer limits cause pad breakout.",
            remediation="Increase pad outer diameter or reduce finished hole drill size.",
            is_mandatory=True,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="mechanical.connector_mating_orientation",
            revision=1,
            domain=ReviewDomain.MECHANICAL,
            title="Connector Mating Direction and Board-Edge Alignment",
            source_doc="Issue #1393 Mechanical Acceptance Contract",
            source_revision="2026.10",
            required_inputs=["connector_mating_specs", "board_outline"],
            units="mm",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale="Connectors must align with board edge and face outwardly for cable entry.",
            remediation="Rotate connector footprint 180 deg or align mating datum with Edge.Cuts.",
            is_mandatory=True,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="cosmetics.schematic_visual_readability",
            revision=1,
            domain=ReviewDomain.SCHEMATIC,
            title="Schematic Readability, Symbol/Text Overlap and Title Block",
            source_doc="KiCad MCP Visual QA Standard",
            source_revision="2026.08",
            required_inputs=["schematic_symbols", "schematic_wires"],
            units=None,
            method=EvaluationMethod.HEURISTIC,
            severity="warning",
            rationale="Schematics must maintain legible text, clean wires, and valid title blocks.",
            remediation="Run sch_straighten_wires and sch_snap_to_grid to fix aesthetic defects.",
            is_mandatory=False,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="cosmetics.pcb_visual_presentation",
            revision=1,
            domain=ReviewDomain.PCB,
            title="PCB Silkscreen Readability, Component Clearance and Pin-1 Indication",
            source_doc="KiCad MCP Visual QA Standard",
            source_revision="2026.08",
            required_inputs=["board_footprints", "board_outline"],
            units="mm",
            method=EvaluationMethod.HEURISTIC,
            severity="warning",
            rationale=(
                "Silkscreen text, component bodies, and pin-1 markers must remain "
                "legible and unclipped."
            ),
            remediation=(
                "Relocate overlapping silkscreen designators and align components within board."
            ),
            is_mandatory=False,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="electrical.component_derating",
            revision=1,
            domain=ReviewDomain.ELECTRICAL,
            title="Component Operating Stress Derating and Ratings Verification",
            source_doc="Component Reliability Derating Guidelines",
            source_revision="2026.01",
            required_inputs=["component_operating_points", "component_ratings"],
            units="pct",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale=(
                "Components must operate below absolute maximum ratings and within "
                "safe reliability derating limits."
            ),
            remediation="Select higher rated component or reduce operating voltage/current/power.",
            is_mandatory=True,
        )
    )

    catalog.register(
        ReviewRule(
            rule_id="thermal.plane_operating_temperature",
            revision=1,
            domain=ReviewDomain.THERMAL,
            title="Copper Plane Steady-State Peak Temperature",
            source_doc="KiCad MCP Thermal Solver Specification",
            source_revision="2026.04",
            required_inputs=["thermal_plane_spec"],
            units="C",
            method=EvaluationMethod.ANALYTICAL,
            severity="error",
            rationale="Peak copper temperature must remain below maximum board/component limit.",
            remediation="Increase copper thickness, expand plane area, or add thermal vias.",
            is_mandatory=True,
        )
    )

    return catalog
