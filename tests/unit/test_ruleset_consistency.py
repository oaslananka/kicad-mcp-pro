"""Repository ruleset desired state must match real CI and fleet governance policy."""

from __future__ import annotations

import itertools
import json
import re
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MAIN_RULESET = ROOT / ".github" / "rulesets" / "main.json"
RELEASE_TAG_RULESET = ROOT / ".github" / "rulesets" / "release-tags.json"
WORKFLOWS = ROOT / ".github" / "workflows"

_MATRIX_REF = re.compile(r"\$\{\{\s*matrix\.([A-Za-z0-9_-]+)\s*\}\}")
_EXPECTED_RELEASE_TAGS = [
    "refs/tags/protocol-schemas-v*",
    "refs/tags/mcp-server-v*",
    "refs/tags/mcp-npm-v*",
    "refs/tags/kicad-mcp-gui-v*",
]


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


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


def _rule(ruleset: dict[str, Any], rule_type: str) -> dict[str, Any]:
    return next(rule for rule in ruleset["rules"] if rule.get("type") == rule_type)


def required_contexts() -> list[str]:
    ruleset = _load(MAIN_RULESET)
    checks = _rule(ruleset, "required_status_checks")["parameters"]["required_status_checks"]
    return [check["context"] for check in checks]


def test_main_ruleset_matches_canonical_fleet_governance_shape() -> None:
    ruleset = _load(MAIN_RULESET)

    assert ruleset["name"] == "main-standard"
    assert ruleset["target"] == "branch"
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"] == {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}}

    assert [rule["type"] for rule in ruleset["rules"]] == [
        "deletion",
        "non_fast_forward",
        "required_linear_history",
        "pull_request",
        "required_status_checks",
    ]

    pull_request = _rule(ruleset, "pull_request")["parameters"]
    assert pull_request == {
        "required_approving_review_count": 0,
        "dismiss_stale_reviews_on_push": False,
        "required_reviewers": [],
        "require_code_owner_review": False,
        "require_last_push_approval": False,
        "required_review_thread_resolution": True,
        "require_extra_approval_for_unattributed_changes": True,
        "allowed_merge_methods": ["squash"],
    }

    assert ruleset["bypass_actors"] == [
        {
            "actor_id": 285490571,
            "actor_type": "User",
            "bypass_mode": "pull_request",
        }
    ]


def test_required_status_check_policy_is_strict_and_creation_safe() -> None:
    parameters = _rule(_load(MAIN_RULESET), "required_status_checks")["parameters"]

    assert parameters["strict_required_status_checks_policy"] is True
    assert parameters["do_not_enforce_on_create"] is False
    assert parameters["required_status_checks"]


def test_ruleset_contexts_are_real_check_names() -> None:
    produced = produced_check_names()
    missing = [ctx for ctx in required_contexts() if ctx not in produced]
    assert not missing, (
        f"Ruleset requires status checks no workflow produces: {missing}. "
        f"Known check names: {sorted(produced)}"
    )


def test_ruleset_defines_required_status_checks() -> None:
    assert required_contexts(), "main ruleset defines no required status checks"


def test_ruleset_does_not_require_live_model_release_policy() -> None:
    assert "Live Model Release Policy" not in required_contexts()


def test_ruleset_requires_sonarcloud_scan() -> None:
    assert "SonarCloud Scan" in required_contexts()


def test_release_tag_ruleset_matches_published_product_families() -> None:
    ruleset = _load(RELEASE_TAG_RULESET)

    assert ruleset["name"] == "release-tags"
    assert ruleset["target"] == "tag"
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"] == {"ref_name": {"include": _EXPECTED_RELEASE_TAGS, "exclude": []}}
    assert [rule["type"] for rule in ruleset["rules"]] == ["deletion", "update"]
    assert ruleset["bypass_actors"] == []
