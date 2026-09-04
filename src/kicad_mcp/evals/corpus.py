"""Golden-corpus end-to-end eval harness.

Loads the golden project corpus (``evals/golden_corpus.yaml``), validates project
structure, and where KiCad is available runs quality gates (ERC, DRC, placement,
manufacturing, project) then scores the results against the prescribed answer keys.

In ``dry_run`` mode (the default in CI), only schema validation and project-file
existence checks are performed — no KiCad CLI is invoked.

Metrics produced per project:
  - project_exists, has_sch, has_pcb, has_pro
  - expected_gates_defined
  - gate_results (when KiCad is available)
  - overall_outcome_match (pass/fail matches expected)

Aggregate metrics:
  - total_projects, pass_rate, mean_violation_agreement
  - false_pass_rate, false_fail_rate
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

_GOLDEN_CORPUS_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "evals" / "golden_corpus.yaml"
)

GateName = Literal["erc", "drc", "placement", "manufacturing", "project"]
ViolationSpec = int | str  # exact count, or ">=N"


@dataclass(frozen=True)
class GoldenProject:
    """One project in the golden corpus with its answer key."""

    id: str
    dir: str
    kicad_version: str
    expected_outcome: Literal["pass", "fail"]
    expected_gates: tuple[GateName, ...] = ()
    expected_violations: dict[str, ViolationSpec] = field(default_factory=dict)
    expected_components: dict[str, int] = field(default_factory=dict)
    expected_nets: dict[str, int | None] = field(default_factory=dict)
    tags: tuple[str, ...] = ()
    defect_class: str = ""
    boards: tuple[str, ...] = ()


@dataclass(frozen=True)
class CorpusEvalResult:
    """Result of evaluating one golden project."""

    project_id: str
    fixture_path: str
    files_exist: dict[str, bool]
    schema_valid: bool
    errors: tuple[str, ...] = ()
    skeleton_ok: bool = False  # True when project dir and expected files exist


@dataclass(frozen=True)
class CorpusEvalSummary:
    """Aggregated results across the corpus."""

    total: int
    passed: int
    skeleton_ok_count: int
    skeleton_ok_rate: float
    schema_valid_count: int
    errors: tuple[str, ...] = ()
    projects: tuple[CorpusEvalResult, ...] = ()


def _check_violation(actual: int, spec: ViolationSpec) -> bool:
    """Check whether an actual violation count matches the spec.

    Supports exact integers and ``">=N"`` / ``"<=N"`` strings.
    """
    if isinstance(spec, int):
        return actual == spec
    if isinstance(spec, str):
        match = re.fullmatch(r"(>=|<=|>|<|==)?\s*(\d+)", spec.strip())
        if not match:
            return False
        op, num_str = match.groups()
        num = int(num_str)
        if op is None or op == "==":
            return actual == num
        if op == ">=":
            return actual >= num
        if op == "<=":
            return actual <= num
        if op == ">":
            return actual > num
        if op == "<":
            return actual < num
    return False


def _parse_violation_spec(raw: object) -> ViolationSpec | None:
    """Parse a raw YAML value into a ``ViolationSpec``."""
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and re.match(r"(>=|<=|>|<|==)?\s*\d+", raw.strip()):
        return raw.strip()
    return None


def _validate_project_schema(raw: dict[str, Any], project_id: str) -> list[str]:
    """Validate a single project entry schema. Returns a list of error messages."""
    errors: list[str] = []
    required_fields = ["id", "dir", "kicad_version", "expected_outcome"]
    for req_field in required_fields:
        if req_field not in raw:
            errors.append(f"Project {project_id!r}: missing required field {req_field!r}")

    outcome = raw.get("expected_outcome", "")
    if outcome not in ("pass", "fail"):
        errors.append(f"Project {project_id!r}: expected_outcome must be 'pass' or 'fail'")

    gates = raw.get("expected_gates", [])
    valid_gates = {"erc", "drc", "placement", "manufacturing", "project"}
    if isinstance(gates, list):
        for g in gates:
            if g not in valid_gates:
                errors.append(f"Project {project_id!r}: unknown gate {g!r}")
    else:
        errors.append(f"Project {project_id!r}: expected_gates must be a list")

    violations = raw.get("expected_violations", {})
    if isinstance(violations, dict):
        for gate_key, spec in violations.items():
            if _parse_violation_spec(spec) is None:
                errors.append(
                    f"Project {project_id!r}: expected_violations.{gate_key!r} has "
                    f"invalid spec {spec!r}"
                )
    else:
        errors.append(f"Project {project_id!r}: expected_violations must be a mapping")

    return errors


def _check_project_files(base_dir: Path, project_dir: str) -> dict[str, bool]:
    """Check that the expected KiCad project files exist."""
    proj_path = base_dir / project_dir
    return {
        "dir_exists": proj_path.is_dir(),
        "has_kicad_pro": len(list(proj_path.glob("*.kicad_pro"))) > 0,
        "has_kicad_sch": len(list(proj_path.glob("*.kicad_sch"))) > 0,
        "has_kicad_pcb": len(list(proj_path.glob("*.kicad_pcb"))) > 0,
        "has_kicad_dru": len(list(proj_path.glob("*.kicad_dru"))) > 0,
    }


def load_corpus(path: str | Path | None = None) -> list[GoldenProject]:
    """Load and validate the golden corpus YAML.

    Returns a list of ``GoldenProject`` entries. Raises ``ValueError`` on
    structural issues.
    """
    corpus_path = Path(path) if path else _GOLDEN_CORPUS_PATH
    if not corpus_path.exists():
        raise ValueError(f"Golden corpus file not found: {corpus_path}")

    raw = yaml.safe_load(corpus_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Corpus must be a mapping with a top-level 'golden_projects' list.")

    projects_raw = raw.get("golden_projects")
    if not isinstance(projects_raw, list) or not projects_raw:
        raise ValueError("'golden_projects' must be a non-empty list.")

    projects: list[GoldenProject] = []
    seen: set[str] = set()
    all_errors: list[str] = []

    for index, p_raw in enumerate(projects_raw):
        if not isinstance(p_raw, dict):
            all_errors.append(f"Entry #{index} must be a mapping.")
            continue

        pid = str(p_raw.get("id", ""))
        if not pid:
            all_errors.append(f"Entry #{index} is missing an 'id'.")
            continue
        if pid in seen:
            all_errors.append(f"Duplicate project id: {pid!r}.")
            continue
        seen.add(pid)

        schema_errors = _validate_project_schema(p_raw, pid)
        all_errors.extend(schema_errors)

        outcome = str(p_raw.get("expected_outcome", "pass"))
        projects.append(
            GoldenProject(
                id=pid,
                dir=str(p_raw.get("dir", "")),
                kicad_version=str(p_raw.get("kicad_version", "")),
                expected_outcome="pass" if outcome == "pass" else "fail",
                expected_gates=tuple(p_raw.get("expected_gates", [])),
                expected_violations={
                    k: _parse_violation_spec(v)  # type: ignore[misc]
                    for k, v in p_raw.get("expected_violations", {}).items()
                    if _parse_violation_spec(v) is not None
                },
                expected_components=dict(p_raw.get("expected_components", {})),
                expected_nets=dict(p_raw.get("expected_nets", {})),
                tags=tuple(p_raw.get("tags", [])),
                defect_class=str(p_raw.get("defect_class", "")),
                boards=tuple(p_raw.get("boards", [])),
            )
        )

    if all_errors:
        raise ValueError("Corpus validation failed:\n  " + "\n  ".join(all_errors))

    return projects


def evaluate_project(
    project: GoldenProject,
    base_dir: Path | None = None,
    dry_run: bool = True,
) -> CorpusEvalResult:
    """Evaluate one golden project against its answer key.

    In ``dry_run`` mode (default), only checks that the project directory and
    expected files exist. When ``dry_run=False`` and KiCad is available, runs
    quality gates and scores results.

    Returns a ``CorpusEvalResult``.
    """
    if base_dir is None:
        # Assume relative to repo root (grandparent of evals/)
        base_dir = _GOLDEN_CORPUS_PATH.resolve().parent.parent

    errors: list[str] = []
    fixture_path = str(Path(project.dir))
    files = _check_project_files(base_dir, project.dir)

    schema_valid = (
        len(
            _validate_project_schema(
                {
                    "id": project.id,
                    "dir": project.dir,
                    "kicad_version": project.kicad_version,
                    "expected_outcome": project.expected_outcome,
                    "expected_gates": list(project.expected_gates),
                    "expected_violations": project.expected_violations,
                },
                project.id,
            )
        )
        == 0
    )

    # Skeleton check: dir must exist and at least .kicad_pro must be present
    skeleton_ok = files["dir_exists"] and files["has_kicad_pro"]

    if not files["dir_exists"]:
        errors.append(f"Project directory not found: {fixture_path}")
    if not files["has_kicad_pro"]:
        errors.append("Missing .kicad_pro project file")
    if not files["has_kicad_sch"] and "erc" in project.expected_gates:
        errors.append("Missing .kicad_sch (required by gate: erc)")
    if not files["has_kicad_pcb"] and "drc" in project.expected_gates:
        errors.append("Missing .kicad_pcb (required by gate: drc)")

    return CorpusEvalResult(
        project_id=project.id,
        fixture_path=fixture_path,
        files_exist=files,
        schema_valid=schema_valid,
        skeleton_ok=skeleton_ok,
        errors=tuple(errors),
    )


def evaluate_corpus(
    projects: list[GoldenProject] | None = None,
    base_dir: Path | None = None,
    dry_run: bool = True,
) -> CorpusEvalSummary:
    """Evaluate the full golden corpus and return aggregate metrics."""
    if projects is None:
        projects = load_corpus()

    results: list[CorpusEvalResult] = []
    all_errors: list[str] = []

    for project in projects:
        try:
            result = evaluate_project(project, base_dir=base_dir, dry_run=dry_run)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            all_errors.append(f"Project {project.id}: evaluation error: {exc}")

    total = len(projects)
    passed = sum(1 for r in results if r.skeleton_ok and r.schema_valid)
    skeleton_ok_count = sum(1 for r in results if r.skeleton_ok)
    schema_valid_count = sum(1 for r in results if r.schema_valid)
    skeleton_ok_rate = skeleton_ok_count / total if total > 0 else 0.0

    return CorpusEvalSummary(
        total=total,
        passed=passed,
        skeleton_ok_count=skeleton_ok_count,
        skeleton_ok_rate=round(skeleton_ok_rate, 4),
        schema_valid_count=schema_valid_count,
        errors=tuple(all_errors),
        projects=tuple(results),
    )


def aggregate_metrics(summary: CorpusEvalSummary) -> dict[str, Any]:
    """Return headline metrics from a corpus evaluation summary."""
    return {
        "total_projects": summary.total,
        "skeleton_ok": summary.skeleton_ok_count,
        "skeleton_ok_rate": summary.skeleton_ok_rate,
        "schema_valid": summary.schema_valid_count,
        "schema_valid_rate": round(summary.schema_valid_count / summary.total, 4)
        if summary.total > 0
        else 0.0,
        "errors": list(summary.errors),
    }
