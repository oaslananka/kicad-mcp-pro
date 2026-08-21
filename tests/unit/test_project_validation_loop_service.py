from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from kicad_mcp.project.validation_loops import (
    AutoFixLoopPayload,
    ProjectValidationLoopService,
)


@dataclass
class Outcome:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class Fixer:
    tool: str
    description: str
    auto_applicable: bool = False
    callable_import: str = ""


async def _value(value: str) -> str:
    return value


async def _ignore_progress(_current: float, _total: float, _message: str) -> None:
    return None


def _service(
    *,
    evaluate_project_gate,
    fixers_for_gate,
    resolve_callable,
) -> ProjectValidationLoopService:
    return ProjectValidationLoopService(
        evaluate_project_gate=evaluate_project_gate,
        fixers_for_gate=fixers_for_gate,
        resolve_callable=resolve_callable,
    )


@pytest.mark.anyio
async def test_auto_fix_loop_applies_fixer_re_evaluates_and_reports_progress() -> None:
    runs = iter(
        [
            [Outcome("Schematic", "FAIL", "unannotated symbols")],
            [Outcome("Placement", "WARN", "review placement")],
        ]
    )
    fixed: list[str] = []
    progress: list[tuple[float, float, str]] = []
    sampled: list[str] = []

    def fixers(name: str) -> list[Fixer]:
        if name == "Schematic":
            return [
                Fixer(
                    "sch_annotate",
                    "Annotate symbols.",
                    True,
                    "tools.schematic:run_auto_annotate",
                )
            ]
        return [Fixer("pcb_place_decoupling_caps", "Move bypass capacitors near ICs.")]

    async def sample(outcome: Outcome) -> str:
        sampled.append(outcome.name)
        return "place caps near the IC"

    async def report(current: float, total: float, message: str) -> None:
        progress.append((current, total, message))

    service = _service(
        evaluate_project_gate=lambda: next(runs),
        fixers_for_gate=fixers,
        resolve_callable=lambda _path: lambda: fixed.append("yes") or "annotated",
    )

    result = await service.auto_fix_loop(
        max_iterations=3,
        sample_guidance=sample,
        report_progress=report,
    )

    assert isinstance(result, AutoFixLoopPayload)
    assert fixed == ["yes"]
    assert sampled == ["Placement"]
    assert result.gate_status == "WARN"
    assert result.iterations_used == 2
    assert result.remaining_issues == 1
    assert result.ready_for_release is False
    assert result.actions[0].agent_tool == "pcb_place_decoupling_caps"
    assert result.actions[0].sampling_guidance == "place caps near the IC"
    assert "Server-side auto-fixes applied:" in result.text
    assert "call pcb_place_decoupling_caps()" in result.text
    assert progress == [
        (0, 100, "Project quality gate is being evaluated..."),
        (25, 100, "Re-evaluating quality gates after iteration 1..."),
        (100, 100, "Project auto-fix loop completed."),
    ]


@pytest.mark.anyio
async def test_auto_fix_loop_resolver_miss_skips_mutation_and_returns_action() -> None:
    service = _service(
        evaluate_project_gate=lambda: [Outcome("PCB", "FAIL", "zones stale")],
        fixers_for_gate=lambda _name: [
            Fixer("pcb_refill_zones", "Refill zones.", True, "tools.pcb:run_auto_refill_zones")
        ],
        resolve_callable=lambda _path: None,
    )

    result = await service.auto_fix_loop(
        max_iterations=4,
        sample_guidance=lambda _outcome: _value(""),
        report_progress=_ignore_progress,
    )

    assert result.iterations_used == 1
    assert result.gate_status == "FAIL"
    assert result.actions[0].agent_tool == "pcb_refill_zones"
    assert "Server-side auto-fixes applied:" not in result.text


@pytest.mark.anyio
async def test_auto_fix_loop_logs_fixer_exception_without_re_evaluating() -> None:
    evaluations = 0

    def evaluate() -> list[Outcome]:
        nonlocal evaluations
        evaluations += 1
        return [Outcome("PCB", "FAIL", "zones stale")]

    def fail() -> object:
        raise RuntimeError("refill failed")

    service = _service(
        evaluate_project_gate=evaluate,
        fixers_for_gate=lambda _name: [
            Fixer("pcb_refill_zones", "Refill zones.", True, "tools.pcb:run_auto_refill_zones")
        ],
        resolve_callable=lambda _path: fail,
    )

    result = await service.auto_fix_loop(
        max_iterations=4,
        sample_guidance=lambda _outcome: _value(""),
        report_progress=_ignore_progress,
    )

    assert evaluations == 1
    assert "Auto-fix 'pcb_refill_zones' for 'PCB' raised: refill failed" in result.text
    assert result.remaining_issues == 1


@pytest.mark.anyio
async def test_auto_fix_loop_clamps_max_iterations_to_one_and_twenty() -> None:
    lower_calls = 0

    def lower_eval() -> list[Outcome]:
        nonlocal lower_calls
        lower_calls += 1
        return [Outcome("PCB", "FAIL", "zones stale")]

    lower = _service(
        evaluate_project_gate=lower_eval,
        fixers_for_gate=lambda _name: [
            Fixer("pcb_refill_zones", "Refill zones.", True, "tools.pcb:run_auto_refill_zones")
        ],
        resolve_callable=lambda _path: lambda: "refilled",
    )
    lower_result = await lower.auto_fix_loop(
        max_iterations=0,
        sample_guidance=lambda _outcome: _value(""),
        report_progress=_ignore_progress,
    )
    assert lower_result.iterations_used == 1
    assert lower_calls == 1

    upper_calls = 0

    def upper_eval() -> list[Outcome]:
        nonlocal upper_calls
        upper_calls += 1
        return [Outcome("PCB", "FAIL", "zones stale")]

    upper = _service(
        evaluate_project_gate=upper_eval,
        fixers_for_gate=lambda _name: [
            Fixer("pcb_refill_zones", "Refill zones.", True, "tools.pcb:run_auto_refill_zones")
        ],
        resolve_callable=lambda _path: lambda: "refilled",
    )
    upper_result = await upper.auto_fix_loop(
        max_iterations=99,
        sample_guidance=lambda _outcome: _value(""),
        report_progress=_ignore_progress,
    )
    assert upper_result.iterations_used == 20
    assert upper_calls == 20


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS", "WARN"], "WARN"),
        (["PASS", "FAIL", "WARN"], "FAIL"),
        (["PASS", "BLOCKED", "FAIL"], "BLOCKED"),
        (["PASS", "EMPTY", "BLOCKED"], "EMPTY"),
        (["PASS"], "PASS"),
    ],
)
def test_full_validation_loop_preserves_status_precedence(
    statuses: list[str], expected: str
) -> None:
    service = _service(
        evaluate_project_gate=lambda: [
            Outcome(f"Gate-{index}", status, status) for index, status in enumerate(statuses)
        ],
        fixers_for_gate=lambda _name: [],
        resolve_callable=lambda _path: None,
    )

    result = service.full_validation_loop(max_iterations=1, fix_tier="suggest")

    assert result.gate_status == expected


def test_full_validation_loop_auto_only_applies_first_auto_fixer_and_re_evaluates() -> None:
    runs = iter(
        [
            [Outcome("Pre-sync", "FAIL", "missing junctions")],
            [Outcome("Pre-sync", "PASS", "safe")],
        ]
    )
    fixed: list[str] = []
    service = _service(
        evaluate_project_gate=lambda: next(runs),
        fixers_for_gate=lambda _name: [
            Fixer(
                "sch_add_missing_junctions",
                "Repair junctions.",
                True,
                "tools.schematic:run_auto_add_missing_junctions",
            )
        ],
        resolve_callable=lambda _path: lambda: fixed.append("fixed") or "junctions repaired",
    )

    result = service.full_validation_loop(max_iterations=3, fix_tier="auto_only")

    assert fixed == ["fixed"]
    assert result.iterations_used == 2
    assert result.gate_status == "PASS"
    assert result.ready_for_release is True
    assert result.remaining_issues == 0
    assert "sch_add_missing_junctions -> junctions repaired" in result.text
    assert "PASS after validation loop." in result.text


def test_full_validation_loop_suggest_never_resolves_or_invokes_fixer() -> None:
    resolved: list[str] = []
    service = _service(
        evaluate_project_gate=lambda: [Outcome("Placement", "FAIL", "caps too far")],
        fixers_for_gate=lambda _name: [
            Fixer("pcb_place_decoupling_caps", "Move bypass capacitors near ICs.")
        ],
        resolve_callable=lambda path: resolved.append(path) or (lambda: "unexpected"),
    )

    result = service.full_validation_loop(max_iterations=5, fix_tier="suggest")

    assert resolved == []
    assert result.iterations_used == 1
    assert result.remaining_issues == 1
    assert result.actions[0].agent_tool == "pcb_place_decoupling_caps"
    assert "Suggested fixes:" in result.text


def test_full_validation_loop_fixer_exception_stops_with_current_action_plan() -> None:
    evaluations = 0

    def evaluate() -> list[Outcome]:
        nonlocal evaluations
        evaluations += 1
        return [Outcome("Pre-sync", "FAIL", "missing junctions")]

    def fail() -> object:
        raise RuntimeError("junction repair failed")

    service = _service(
        evaluate_project_gate=evaluate,
        fixers_for_gate=lambda _name: [
            Fixer(
                "sch_add_missing_junctions",
                "Repair junctions.",
                True,
                "tools.schematic:run_auto_add_missing_junctions",
            )
        ],
        resolve_callable=lambda _path: fail,
    )

    result = service.full_validation_loop(max_iterations=5, fix_tier="auto_only")

    assert evaluations == 1
    assert result.iterations_used == 1
    assert "sch_add_missing_junctions raised junction repair failed" in result.text
    assert result.actions[0].agent_tool == "sch_add_missing_junctions"
