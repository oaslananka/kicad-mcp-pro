"""Ensure the staged Renovate policy cannot silently auto-merge changes."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKS = {
    "mcp-server (ubuntu-24.04)",
    "mcp-server (windows-2025)",
    "mcp-server (macos-15)",
    "mcp-npm (ubuntu-24.04)",
    "mcp-npm (windows-2025)",
    "mcp-npm (macos-15)",
    "protocol-schemas",
    "scan",
    "analyze (python)",
    "analyze (javascript-typescript)",
    "Required PR Gate",
    "SonarCloud Scan",
    "dependency-review",
}


def _config() -> dict[str, object]:
    return json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))


def _mergify() -> dict[str, object]:
    return yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))


def test_pilot_disabled_dependabot_preserved() -> None:
    config = _config()
    assert config["enabled"] is False
    assert config["automerge"] is False
    assert config["platformAutomerge"] is False
    assert config["prConcurrentLimit"] <= 2
    assert config["prHourlyLimit"] <= 1
    assert config["separateMinorPatch"] is True
    assert (ROOT / ".github/dependabot.yml").is_file()
    assert set(config["enabledManagers"]) >= {"pep621", "npm", "cargo"}


def test_security_major_lockfile_policy() -> None:
    config = _config()
    assert config["vulnerabilityAlerts"]["enabled"] is True
    assert config["vulnerabilityAlerts"]["minimumReleaseAge"] is None
    assert config["lockFileMaintenance"]["enabled"] is False
    assert config["lockFileMaintenance"]["automerge"] is False
    major = next(rule for rule in config["packageRules"] if "major" in rule["matchUpdateTypes"])
    assert major["dependencyDashboardApproval"] is True
    assert major["automerge"] is False


def test_renovate_queue_requires_manual_label_and_full_ci() -> None:
    mergify = _mergify()
    queues = {rule["name"]: rule for rule in mergify["queue_rules"]}
    assert "safe-dependencies" in queues
    assert "renovate-pilot-safe" in queues
    pilot = queues["renovate-pilot-safe"]
    for kind in ("merge_conditions", "queue_conditions"):
        conditions = set(pilot[kind])
        assert {
            "author = renovate[bot]",
            "base = main",
            "-draft",
            "label = renovate-patch",
            "label = renovate-pilot-approved",
            "head ~= ^renovate/",
            "#review-threads-unresolved = 0",
        } <= conditions
        assert {f"check-success = {name}" for name in CHECKS} <= conditions
    rules = {rule["name"]: rule for rule in mergify["pull_request_rules"]}
    assert "Queue safe grouped Dependabot updates" in rules
    action = rules["Queue explicitly approved Renovate patch pilot PRs"]
    assert "label = renovate-pilot-approved" in action["conditions"]
    assert action["actions"]["queue"]["name"] == "renovate-pilot-safe"


def test_maintainer_queue_excludes_bots_and_stays_manual() -> None:
    mergify = _mergify()
    maintainer = next(rule for rule in mergify["queue_rules"] if rule["name"] == "maintainer")
    for kind in ("merge_conditions", "queue_conditions"):
        assert "author != dependabot[bot]" in maintainer[kind]
        assert "author != renovate[bot]" in maintainer[kind]
    assert all(
        rule["actions"]["queue"]["name"] != "maintainer" for rule in mergify["pull_request_rules"]
    )
