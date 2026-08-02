"""Branch-protection ruleset must reference real CI check names (work order P5-T4).

A required status check whose context never matches a produced GitHub check-run
name silently blocks every PR to ``main`` (or is quietly ignored). This guards
``.github/rulesets/main.json`` against drifting from the workflow job names — the
exact failure that left ``mcp-server (windows-2025-vs2026)`` required after the CI
matrix moved to ``windows-2025``.
"""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
RULESET = ROOT / ".github" / "rulesets" / "main.json"
WORKFLOWS = ROOT / ".github" / "workflows"

_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")


def _matrix_combinations(strategy: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate the matrix combinations GitHub would expand for a job."""
    matrix = strategy.get("matrix") if isinstance(strategy, dict) else None
    if not isinstance(matrix, dict):
        return [{}]
    include = matrix.get("include")
    axes = {key: val for key, val in matrix.items() if key != "include" and isinstance(val, list)}
    combos: list[dict[str, Any]] = []
    if axes:
        keys = list(axes)
        for values in itertools.product(*(axes[key] for key in keys)):
            combos.append(dict(zip(keys, values, strict=True)))
    if isinstance(include, list):
        combos.extend(dict(entry) for entry in include if isinstance(entry, dict))
    return combos or [{}]


def _check_name(job_id: str, job: dict[str, Any], combo: dict[str, Any]) -> str:
    """Compute the GitHub check-run name for one job/matrix combination."""
    name = job.get("name")
    if isinstance(name, str):
        return _MATRIX_REF.sub(lambda m: str(combo.get(m.group(1), m.group(0))), name)
    if combo:
        return f"{job_id} ({', '.join(str(value) for value in combo.values())})"
    return job_id


def produced_check_names() -> set[str]:
    names: set[str] = set()
    workflow_files = [*sorted(WORKFLOWS.glob("*.yml")), *sorted(WORKFLOWS.glob("*.yaml"))]
    for path in workflow_files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for job_id, job in (data.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for combo in _matrix_combinations(job.get("strategy", {})):
                names.add(_check_name(job_id, job, combo))
    return names


def required_contexts() -> list[str]:
    ruleset = json.loads(RULESET.read_text(encoding="utf-8"))
    for rule in ruleset.get("rules", []):
        if rule.get("type") == "required_status_checks":
            checks = rule["parameters"]["required_status_checks"]
            return [check["context"] for check in checks]
    return []


def test_ruleset_contexts_are_real_check_names() -> None:
    produced = produced_check_names()
    missing = [ctx for ctx in required_contexts() if ctx not in produced]
    assert not missing, (
        f"Ruleset requires status checks no workflow produces: {missing}. "
        f"Known check names: {sorted(produced)}"
    )


def test_ruleset_defines_required_status_checks() -> None:
    assert required_contexts(), "main ruleset defines no required status checks"


def test_ruleset_requires_live_model_release_policy() -> None:
    assert "Live Model Release Policy" in required_contexts()
