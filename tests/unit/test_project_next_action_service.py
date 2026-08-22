from __future__ import annotations

from types import SimpleNamespace


def _service(outcomes):
    from kicad_mcp.project.next_action import ProjectNextActionService

    return ProjectNextActionService(evaluate_project_gate=lambda: outcomes)


def test_next_action_service_returns_release_when_all_gates_pass() -> None:
    payload = _service(
        [SimpleNamespace(name="PCB", status="PASS", summary="ok", details=[])]
    ).next_action()
    assert payload.status == "PASS"
    assert payload.verdict == "PASS"
    assert payload.suggested_tool == "export_manufacturing_package()"
    assert payload.next_action == "export_manufacturing_package()"


def test_next_action_service_prioritizes_blocked_gate_and_tagged_reason() -> None:
    payload = _service(
        [
            SimpleNamespace(name="PCB", status="FAIL", summary="pcb", details=["FAIL: clearance"]),
            SimpleNamespace(
                name="Schematic", status="BLOCKED", summary="erc", details=["BLOCKED: no project"]
            ),
        ]
    ).next_action()
    assert payload.status == "BLOCKED"
    assert payload.gate == "Schematic"
    assert payload.reason == "no project"
    assert payload.suggested_tool == "run_erc()"
    assert payload.findings[0].suggested_fix is not None
    assert payload.findings[0].suggested_fix.tool == "run_erc"


def test_next_action_service_maps_empty_to_warn() -> None:
    payload = _service(
        [SimpleNamespace(name="Placement", status="EMPTY", summary="empty", details=[])]
    ).next_action()
    assert payload.verdict == "WARN"
    assert payload.findings[0].severity == "warning"


def test_next_action_service_fails_closed_when_gate_evaluation_raises() -> None:
    from kicad_mcp.project.next_action import ProjectNextActionService

    def boom():
        raise RuntimeError("offline")

    payload = ProjectNextActionService(evaluate_project_gate=boom).next_action()
    assert payload.status == "BLOCKED"
    assert payload.verdict == "FAIL"
    assert payload.suggested_tool == "kicad_get_project_info()"
    assert "offline" in payload.reason
