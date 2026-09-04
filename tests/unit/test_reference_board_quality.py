from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def _minimal_contract() -> dict[str, object]:
    return {
        "schema_version": "pcb-reference-board-quality.v1",
        "board_id": "esp32-c6-usbc",
        "benchmark_version": "v1",
        "rules": [
            {
                "id": "component-u1",
                "type": "schematic_component",
                "reference": "U1",
                "allowed_lib_ids": ["RF_Module:ESP32-C6-MINI-1"],
            }
        ],
    }


def test_quality_contract_parses_strict_reviewed_rule() -> None:
    from kicad_mcp.evals.reference_board_quality import parse_quality_contract

    contract = parse_quality_contract(_minimal_contract())
    assert contract.board_id == "esp32-c6-usbc"
    assert contract.benchmark_version == "v1"
    assert contract.rules[0].id == "component-u1"
    assert contract.rules[0].required is True


def test_quality_contract_rejects_unknown_fields_and_rule_types() -> None:
    from kicad_mcp.evals.reference_board_quality import parse_quality_contract

    payload = _minimal_contract()
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        parse_quality_contract(payload)

    payload = _minimal_contract()
    rules = list(payload["rules"])
    rules[0] = {"id": "bad", "type": "shell_command", "command": "echo nope"}
    payload["rules"] = rules
    with pytest.raises(ValidationError):
        parse_quality_contract(payload)


def test_quality_score_render_is_deterministic_and_sanitized() -> None:
    from kicad_mcp.evals.reference_board_quality import (
        BoardQualityScore,
        QualityRuleResult,
        render_quality_score,
    )

    score = BoardQualityScore(
        board_id="esp32-c6-usbc",
        benchmark_version="v1",
        attempt_id="attempt-001",
        source_revision="a" * 40,
        required_rule_count=2,
        passed_required_rule_count=1,
        quality_score_percent=50.0,
        overall_pass=False,
        results=(
            QualityRuleResult(id="a", type="artifact", status="pass", reason_code="matched"),
            QualityRuleResult(
                id="b", type="artifact", status="fail", reason_code="artifact_missing"
            ),
        ),
    )
    rendered = render_quality_score(score)
    assert rendered == render_quality_score(score)
    assert json.loads(rendered)["overall_pass"] is False
    assert "C:\\Users" not in rendered


def test_schematic_rules_use_semantic_parser_fixture() -> None:
    from pathlib import Path

    from kicad_mcp.evals.reference_board_quality import (
        SchematicComponentRule,
        SchematicNetRule,
        evaluate_schematic_rule,
    )
    from kicad_mcp.ir.from_kicad import parse_schematic

    path = (
        Path(__file__).parents[1]
        / "fixtures/benchmark_projects/fail_sismosmart_like_label_only/demo.kicad_sch"
    )
    circuit = parse_schematic(path, load_pin_metadata=False)
    component = evaluate_schematic_rule(
        SchematicComponentRule(
            id="u1",
            type="schematic_component",
            reference="U1",
            allowed_lib_ids=("RF_Module:ESP32-S3-WROOM-1",),
        ),
        circuit,
    )
    net = evaluate_schematic_rule(
        SchematicNetRule(id="vbus", type="schematic_net", net_name="VBUS"), circuit
    )
    assert (component.status, component.reason_code) == ("pass", "matched")
    assert (net.status, net.reason_code) == ("pass", "matched")


def test_pcb_rules_reuse_existing_footprint_and_outline_parsers() -> None:
    from pathlib import Path

    from kicad_mcp.evals.reference_board_quality import (
        BoardOutlineRule,
        PcbFootprintRule,
        PcbNetRule,
        evaluate_pcb_rule,
    )

    root = Path(__file__).parents[1] / "fixtures/benchmark_projects"
    minimal = (root / "pass_minimal_mcu_board/demo.kicad_pcb").read_text(encoding="utf-8")
    footprint = evaluate_pcb_rule(
        PcbFootprintRule(
            id="u1",
            type="pcb_footprint",
            reference="U1",
            allowed_footprints=("Package_QFP:TQFP-48",),
        ),
        minimal,
    )
    outline = evaluate_pcb_rule(
        BoardOutlineRule(
            id="outline",
            type="board_outline",
            min_width_mm=29.0,
            max_width_mm=31.0,
            min_height_mm=19.0,
            max_height_mm=21.0,
        ),
        minimal,
    )
    dirty = (root / "fail_dirty_transfer_wrong_pad_nets/demo.kicad_pcb").read_text(encoding="utf-8")
    net = evaluate_pcb_rule(
        PcbNetRule(id="vin", type="pcb_net", net_name="VIN", required_references=("R1",)),
        dirty,
    )
    assert (footprint.status, outline.status, net.status) == ("pass", "pass", "pass")


def _quality_attempt():
    from kicad_mcp.evals.task_outcomes import (
        AttemptRecord,
        StageEvidence,
        TimingEvidence,
        ValidationEvidence,
    )

    return AttemptRecord(
        attempt_id="attempt-001",
        task_id="board-v1",
        task_class="pcb-authoring",
        task_contract_version="v1",
        benchmark_id="pcb-reference-suite",
        benchmark_version="v1",
        source_revision="a" * 40,
        kicad_version="10.0.6",
        toolchain_contract="toolchain-v1",
        mcp_profile="pcb_layout",
        operating_mode="write",
        starting_state_digest="sha256:" + "b" * 64,
        timing=TimingEvidence(
            started_at="2026-09-04T00:00:00+03:00", ended_at="2026-09-04T00:01:00+03:00"
        ),
        classification="success",
        retry_count=0,
        start_state="clean",
        manual_repair=False,
        stages=(StageEvidence(stage="drc", outcome="passed"),),
        validations=(
            ValidationEvidence(
                kind="drc",
                required=True,
                execution_attempted=True,
                execution_completed=True,
                result_consumed=True,
                disposition="resolved",
            ),
        ),
    )


def test_attempt_validation_rule_uses_canonical_attempt_evidence() -> None:
    from kicad_mcp.evals.reference_board_quality import AttemptValidationRule, evaluate_attempt_rule

    attempt = _quality_attempt()
    passed = evaluate_attempt_rule(
        AttemptValidationRule(id="drc", type="attempt_validation", validation_kind="drc"), attempt
    )
    failed = evaluate_attempt_rule(
        AttemptValidationRule(id="erc", type="attempt_validation", validation_kind="erc"), attempt
    )
    assert (passed.status, passed.reason_code) == ("pass", "matched")
    assert (failed.status, failed.reason_code) == ("fail", "validation_missing")


def test_artifact_rule_requires_nonempty_regular_artifact(tmp_path) -> None:
    from kicad_mcp.evals.reference_board_quality import ArtifactRule, evaluate_artifact_rule

    (tmp_path / "report.txt").write_text("ok", encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    (tmp_path / "plots").mkdir()
    assert (
        evaluate_artifact_rule(
            ArtifactRule(id="report", type="artifact", path="report.txt", kind="file"), tmp_path
        ).status
        == "pass"
    )
    empty = evaluate_artifact_rule(
        ArtifactRule(id="empty", type="artifact", path="empty.txt", kind="file"), tmp_path
    )
    missing = evaluate_artifact_rule(
        ArtifactRule(id="missing", type="artifact", path="missing.txt", kind="file"), tmp_path
    )
    empty_directory = evaluate_artifact_rule(
        ArtifactRule(id="plots", type="artifact", path="plots", kind="directory"), tmp_path
    )
    (tmp_path / "plots" / "summary.json").write_text("{}", encoding="utf-8")
    directory = evaluate_artifact_rule(
        ArtifactRule(id="plots", type="artifact", path="plots", kind="directory"), tmp_path
    )
    assert (
        empty.reason_code,
        missing.reason_code,
        empty_directory.reason_code,
        directory.status,
    ) == ("artifact_empty", "artifact_missing", "artifact_empty", "pass")


def _write_scoring_bundle(tmp_path, *, board_id: str = "board-a", rules: list[dict[str, object]]):
    import kicad_mcp.evals as evals

    root = tmp_path / "board-a" / "v1"
    attempt_dir = root / "attempts" / "attempt-001"
    attempt_dir.mkdir(parents=True)
    requirements = {stage: "not_applicable" for stage in evals.ALL_TASK_STAGES}
    requirements["drc"] = "required"
    contract = evals.BenchmarkContract(
        benchmark_id="pcb-reference-suite",
        benchmark_version="v1",
        tasks=(
            evals.TaskContract(
                task_id="board-v1",
                task_class="pcb-authoring",
                version="v1",
                stage_requirements=requirements,
            ),
        ),
        evidence_sufficiency=evals.EvidenceSufficiencyContract(
            minimum_valid_attempts=1,
            minimum_valid_attempts_by_task_class={"pcb-authoring": 1},
            minimum_recovery_required_mutations=0,
            minimum_drc_required_tasks=1,
            minimum_manufacturing_release_tasks=0,
        ),
    )
    (root / "benchmark.json").write_text(
        evals.render_benchmark_contract(contract), encoding="utf-8"
    )
    (attempt_dir / "attempt.json").write_text(
        evals.render_attempt_record(_quality_attempt()), encoding="utf-8"
    )
    (root / "quality-gates.json").write_text(
        json.dumps(
            {
                "schema_version": "pcb-reference-board-quality.v1",
                "board_id": board_id,
                "benchmark_version": "v1",
                "rules": rules,
            }
        ),
        encoding="utf-8",
    )
    return root, attempt_dir


def test_score_reference_board_attempt_fails_closed_on_identity_mismatch(tmp_path) -> None:
    from kicad_mcp.evals.reference_board_quality import score_reference_board_attempt

    root, attempt_dir = _write_scoring_bundle(
        tmp_path,
        board_id="wrong-board",
        rules=[{"id": "proof", "type": "artifact", "path": "proof.txt", "kind": "file"}],
    )
    (attempt_dir / "proof.txt").write_text("ok", encoding="utf-8")
    score = score_reference_board_attempt(root, "attempt-001")
    assert score.overall_pass is False
    assert score.results[0].reason_code == "evidence_identity_mismatch"


def test_score_reference_board_attempt_reports_missing_design_evidence(tmp_path) -> None:
    from kicad_mcp.evals.reference_board_quality import score_reference_board_attempt

    root, _attempt_dir = _write_scoring_bundle(
        tmp_path,
        rules=[
            {
                "id": "u1",
                "type": "schematic_component",
                "reference": "U1",
                "allowed_lib_ids": ["RF_Module:ESP32-C6-MINI-1"],
            }
        ],
    )
    score = score_reference_board_attempt(root, "attempt-001")
    assert score.overall_pass is False
    assert score.results[0].reason_code == "evidence_missing"


def test_score_reference_board_attempt_requires_every_required_rule(tmp_path) -> None:
    from kicad_mcp.evals.reference_board_quality import score_reference_board_attempt

    root, attempt_dir = _write_scoring_bundle(
        tmp_path,
        rules=[
            {"id": "present", "type": "artifact", "path": "present.txt", "kind": "file"},
            {"id": "missing", "type": "artifact", "path": "missing.txt", "kind": "file"},
        ],
    )
    (attempt_dir / "present.txt").write_text("ok", encoding="utf-8")
    score = score_reference_board_attempt(root, "attempt-001")
    assert score.overall_pass is False
    assert score.passed_required_rule_count == 1
    assert score.required_rule_count == 2
    assert score.quality_score_percent == 50.0


def test_score_reference_board_cli_writes_only_canonical_report(tmp_path) -> None:
    import subprocess
    import sys

    root, attempt_dir = _write_scoring_bundle(
        tmp_path,
        rules=[{"id": "proof", "type": "artifact", "path": "proof.txt", "kind": "file"}],
    )
    (attempt_dir / "proof.txt").write_text("ok", encoding="utf-8")
    repo_root = Path(__file__).parents[2]
    command = [
        sys.executable,
        str(repo_root / "scripts/score_reference_board_attempt.py"),
        str(root),
        "attempt-001",
    ]
    passed = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
    output = attempt_dir / "board-quality-score.json"
    assert passed.returncode == 0
    assert json.loads(output.read_text(encoding="utf-8"))["overall_pass"] is True

    (attempt_dir / "proof.txt").unlink()
    failed = subprocess.run(command, cwd=repo_root, check=False, capture_output=True, text=True)
    assert failed.returncode == 1
    assert json.loads(output.read_text(encoding="utf-8"))["overall_pass"] is False


def test_score_reference_board_attempt_rejects_noncanonical_attempt_id(tmp_path) -> None:
    from kicad_mcp.evals.reference_board_quality import score_reference_board_attempt

    root, _attempt_dir = _write_scoring_bundle(
        tmp_path,
        rules=[{"id": "proof", "type": "artifact", "path": "proof.txt", "kind": "file"}],
    )
    with pytest.raises(ValueError, match="attempt id"):
        score_reference_board_attempt(root, "../attempt-001")


@pytest.mark.parametrize(
    ("board_id", "max_width", "max_height"),
    [
        ("esp32-c6-usbc", 50.0, 32.0),
        ("stm32f072-usbc", 60.0, 36.0),
        ("rp2350-usbc", 58.0, 34.0),
    ],
)
def test_committed_reference_board_quality_contracts_are_valid(
    board_id: str, max_width: float, max_height: float
) -> None:
    from kicad_mcp.evals.reference_board_quality import BoardOutlineRule, parse_quality_contract

    root = Path(__file__).parents[2] / "docs" / "evidence" / "reference-boards" / board_id / "v1"
    payload = json.loads((root / "quality-gates.json").read_text(encoding="utf-8"))
    contract = parse_quality_contract(payload)
    outline = next(rule for rule in contract.rules if isinstance(rule, BoardOutlineRule))
    assert (contract.board_id, contract.benchmark_version) == (board_id, "v1")
    assert (outline.max_width_mm, outline.max_height_mm) == (max_width, max_height)


def test_quality_contract_validators_reject_invalid_models() -> None:
    from kicad_mcp.evals.reference_board_quality import (
        ArtifactRule,
        BoardOutlineRule,
        BoardQualityContract,
        SchematicComponentRule,
    )

    with pytest.raises(ValidationError):
        SchematicComponentRule(id="u1", type="schematic_component", reference="U1")
    with pytest.raises(ValidationError):
        BoardOutlineRule(id="width", type="board_outline", min_width_mm=2.0, max_width_mm=1.0)
    with pytest.raises(ValidationError):
        BoardOutlineRule(id="height", type="board_outline", min_height_mm=2.0, max_height_mm=1.0)
    with pytest.raises(ValidationError):
        ArtifactRule(id="escape", type="artifact", path="../proof.txt", kind="file")

    rule = ArtifactRule(id="proof", type="artifact", path="proof.txt", kind="file")
    with pytest.raises(ValidationError):
        BoardQualityContract(board_id="board-a", benchmark_version="v1", rules=(rule, rule))


def test_quality_score_validator_rejects_inconsistent_summary_fields() -> None:
    from kicad_mcp.evals.reference_board_quality import BoardQualityScore

    base = {
        "board_id": "board-a",
        "benchmark_version": "v1",
        "attempt_id": "attempt-001",
        "source_revision": "a" * 40,
        "required_rule_count": 2,
        "passed_required_rule_count": 1,
        "quality_score_percent": 50.0,
        "overall_pass": False,
        "results": [
            {"id": "a", "type": "artifact", "status": "pass", "reason_code": "matched"},
            {
                "id": "b",
                "type": "artifact",
                "status": "fail",
                "reason_code": "artifact_missing",
            },
        ],
    }
    overrides = (
        {"passed_required_rule_count": 3},
        {"required_rule_count": 3},
        {"passed_required_rule_count": 0},
        {"quality_score_percent": 49.0},
        {"overall_pass": True},
    )
    for update in overrides:
        payload = dict(base)
        payload.update(update)
        with pytest.raises(ValidationError):
            BoardQualityScore.model_validate(payload)


def test_pcb_rules_fail_closed_on_missing_or_mismatched_evidence() -> None:
    from kicad_mcp.evals.reference_board_quality import (
        BoardOutlineRule,
        PcbFootprintRule,
        PcbNetRule,
        evaluate_pcb_rule,
    )

    root = Path(__file__).parents[1] / "fixtures/benchmark_projects"
    minimal = (root / "pass_minimal_mcu_board/demo.kicad_pcb").read_text(encoding="utf-8")
    dirty = (root / "fail_dirty_transfer_wrong_pad_nets/demo.kicad_pcb").read_text(encoding="utf-8")
    missing_footprint = evaluate_pcb_rule(
        PcbFootprintRule(
            id="missing", type="pcb_footprint", reference="Z99", allowed_footprints=("x",)
        ),
        minimal,
    )
    mismatched_footprint = evaluate_pcb_rule(
        PcbFootprintRule(
            id="mismatch", type="pcb_footprint", reference="U1", allowed_footprints=("x",)
        ),
        minimal,
    )
    missing_net = evaluate_pcb_rule(
        PcbNetRule(id="missing-net", type="pcb_net", net_name="NO_SUCH_NET"), minimal
    )
    mismatched_net = evaluate_pcb_rule(
        PcbNetRule(id="mismatch-net", type="pcb_net", net_name="VIN", required_references=("Z99",)),
        dirty,
    )
    missing_outline = evaluate_pcb_rule(
        BoardOutlineRule(id="outline", type="board_outline", max_width_mm=50.0),
        "(kicad_pcb (version 20240108))",
    )
    assert (
        missing_footprint.reason_code,
        mismatched_footprint.reason_code,
        missing_net.reason_code,
        mismatched_net.reason_code,
        missing_outline.reason_code,
    ) == (
        "footprint_missing",
        "identity_mismatch",
        "net_missing",
        "net_membership_mismatch",
        "outline_missing",
    )
