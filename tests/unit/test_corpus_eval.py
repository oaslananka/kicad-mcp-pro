"""Tests for the golden-corpus eval harness."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kicad_mcp.evals.corpus import (
    GoldenProject,
    _check_violation,
    _validate_project_schema,
    aggregate_metrics,
    evaluate_corpus,
    evaluate_project,
    load_corpus,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_GOLDEN_CORPUS_PATH = _REPO_ROOT / "evals" / "golden_corpus.yaml"


# ── Schema validation ──────────────────────────────────────────────────────────


class TestValidateProjectSchema:
    def test_valid_pass_project(self) -> None:
        raw = {
            "id": "test_board",
            "dir": "fixtures/test_board",
            "kicad_version": ">=9.0",
            "expected_outcome": "pass",
            "expected_gates": ["erc", "drc"],
            "expected_violations": {"erc": 0, "drc": 0},
        }
        errors = _validate_project_schema(raw, "test_board")
        assert errors == []

    def test_valid_fail_project(self) -> None:
        raw = {
            "id": "bad_board",
            "dir": "fixtures/bad_board",
            "kicad_version": ">=9.0",
            "expected_outcome": "fail",
            "expected_gates": ["placement"],
            "expected_violations": {"placement": ">=1"},
        }
        errors = _validate_project_schema(raw, "bad_board")
        assert errors == []

    def test_invalid_outcome(self) -> None:
        raw = {
            "id": "x",
            "dir": "x",
            "kicad_version": ">=9.0",
            "expected_outcome": "maybe",
            "expected_gates": ["drc"],
            "expected_violations": {"drc": 0},
        }
        errors = _validate_project_schema(raw, "x")
        assert any("expected_outcome" in e for e in errors)

    def test_unknown_gate(self) -> None:
        raw = {
            "id": "x",
            "dir": "x",
            "kicad_version": ">=9.0",
            "expected_outcome": "pass",
            "expected_gates": ["thermal_simulation"],
            "expected_violations": {},
        }
        errors = _validate_project_schema(raw, "x")
        assert any("thermal_simulation" in e for e in errors)

    def test_missing_required_fields(self) -> None:
        errors = _validate_project_schema({"id": "x"}, "x")
        missing = [e for e in errors if "missing required field" in e]
        assert len(missing) >= 3  # dir, kicad_version, expected_outcome

    @pytest.mark.parametrize(
        ("gates", "violations", "expected"),
        [
            (
                ["erc", "unknown"],
                {"drc": "n/a"},
                (
                    "Project 'probe': unknown gate 'unknown'",
                    "Project 'probe': expected_violations.'drc' has invalid spec 'n/a'",
                ),
            ),
            (
                "erc",
                [],
                (
                    "Project 'probe': expected_gates must be a list",
                    "Project 'probe': expected_violations must be a mapping",
                ),
            ),
            (["erc"], {"erc": 0, "drc": ">=2"}, ()),
            (
                [],
                {"drc": object()},
                ("Project 'probe': expected_violations.'drc' has invalid spec ",),
            ),
        ],
    )
    def test_schema_error_order_and_message_contract(
        self, gates: object, violations: object, expected: tuple[str, ...]
    ) -> None:
        raw = {
            "id": "probe",
            "dir": "fixtures/probe",
            "kicad_version": "10.0.x",
            "expected_outcome": "pass",
            "expected_gates": gates,
            "expected_violations": violations,
        }
        errors = _validate_project_schema(raw, "probe")
        assert len(errors) == len(expected)
        for actual, prefix in zip(errors, expected, strict=True):
            assert actual.startswith(prefix)


# ── Violation matching ────────────────────────────────────────────────────────


class TestCheckViolation:
    def test_exact_match(self) -> None:
        assert _check_violation(0, 0) is True
        assert _check_violation(3, 3) is True
        assert _check_violation(3, 5) is False

    def test_gte_string(self) -> None:
        assert _check_violation(5, ">=1") is True
        assert _check_violation(1, ">=1") is True
        assert _check_violation(0, ">=1") is False

    def test_lte_string(self) -> None:
        assert _check_violation(0, "<=3") is True
        assert _check_violation(3, "<=3") is True
        assert _check_violation(4, "<=3") is False

    def test_gt_lt(self) -> None:
        assert _check_violation(5, ">3") is True
        assert _check_violation(3, ">3") is False
        assert _check_violation(2, "<3") is True
        assert _check_violation(3, "<3") is False

    def test_bare_number_string(self) -> None:
        assert _check_violation(0, "0") is True
        assert _check_violation(1, "1") is True
        assert _check_violation(2, "1") is False


# ── Load corpus ───────────────────────────────────────────────────────────────


class TestLoadCorpus:
    def test_loads_all_projects(self) -> None:
        projects = load_corpus()
        assert len(projects) >= 12
        ids = {p.id for p in projects}
        assert "pass_minimal_mcu_board" in ids
        assert "fail_label_only_schematic" in ids

    def test_load_sets_fields(self) -> None:
        projects = load_corpus()
        mcu = next(p for p in projects if p.id == "pass_minimal_mcu_board")
        assert mcu.expected_outcome == "pass"
        assert "erc" in mcu.expected_gates
        assert mcu.expected_violations.get("erc") == 0

    def test_non_existent_path_raises(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            load_corpus("/nonexistent/path.yaml")

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("not_a_list: true", encoding="utf-8")
        with pytest.raises(ValueError, match="golden_projects"):
            load_corpus(str(bad))


# ── Evaluate project (dry-run) ────────────────────────────────────────────────


class TestEvaluateProject:
    def test_existing_project_passes_skeleton(self) -> None:
        projects = load_corpus()
        mcu = next(p for p in projects if p.id == "pass_minimal_mcu_board")
        result = evaluate_project(mcu, base_dir=_REPO_ROOT, dry_run=True)
        assert result.skeleton_ok is True
        assert result.schema_valid is True
        assert len(result.errors) == 0

    def test_nonexistent_project_fails_skeleton(self) -> None:
        fake = GoldenProject(
            id="nonexistent",
            dir="tests/fixtures/benchmark_projects/DOES_NOT_EXIST",
            kicad_version=">=9.0",
            expected_outcome="pass",
            expected_gates=("drc",),
            expected_violations={"drc": 0},
        )
        result = evaluate_project(fake, base_dir=_REPO_ROOT, dry_run=True)
        assert result.skeleton_ok is False
        assert any("not found" in e for e in result.errors)

    def test_fail_case_skeleton_ok(self) -> None:
        projects = load_corpus()
        fail = next(p for p in projects if p.id == "fail_bad_decoupling_placement")
        result = evaluate_project(fail, base_dir=_REPO_ROOT, dry_run=True)
        assert result.skeleton_ok is True


# ── Evaluate corpus ───────────────────────────────────────────────────────────


class TestEvaluateCorpus:
    def test_dry_run_returns_summary(self) -> None:
        summary = evaluate_corpus(dry_run=True)
        assert summary.total >= 12
        assert summary.skeleton_ok_count >= 10  # most projects should exist
        assert 0.0 < summary.skeleton_ok_rate <= 1.0

    def test_aggregate_metrics_shape(self) -> None:
        summary = evaluate_corpus(dry_run=True)
        metrics = aggregate_metrics(summary)
        assert metrics["total_projects"] >= 12
        assert metrics["skeleton_ok"] >= 10
        assert "skeleton_ok_rate" in metrics
        assert "schema_valid" in metrics


# ── Corpus file integrity ─────────────────────────────────────────────────────


class TestCorpusFileIntegrity:
    """The golden_corpus.yaml itself must exist and have valid entries."""

    def test_corpus_file_exists(self) -> None:
        assert _GOLDEN_CORPUS_PATH.exists(), f"Golden corpus not found at {_GOLDEN_CORPUS_PATH}"

    def test_corpus_file_valid_yaml(self) -> None:
        raw = yaml.safe_load(_GOLDEN_CORPUS_PATH.read_text(encoding="utf-8"))
        assert isinstance(raw, dict)
        assert "golden_projects" in raw
        assert len(raw["golden_projects"]) >= 1

    def test_every_fixture_dir_exists(self) -> None:
        """Every project's fixture directory must exist relative to repo root."""
        projects = load_corpus()
        for p in projects:
            fixture = _REPO_ROOT / p.dir
            assert fixture.is_dir(), f"Project {p.id!r}: fixture directory not found at {fixture}"
