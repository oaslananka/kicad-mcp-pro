"""Fail-closed cutover checks without any GitHub publish side effects."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.check_release_draft_cutover import _PUBLISHERS, validate_cutover

ROOT = Path(__file__).resolve().parents[2]


def _fixture(tmp_path: Path) -> Path:
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "actions-policy.json").write_text(
        json.dumps({"release_asset_mutations": [{"issue": "#1179"}]}), encoding="utf-8"
    )
    shutil.copy2(ROOT / "release-please-config.json", tmp_path / "release-please-config.json")
    for filename in (*_PUBLISHERS, "publish-release.yml"):
        shutil.copy2(
            ROOT / ".github" / "workflows" / filename,
            tmp_path / ".github" / "workflows" / filename,
        )
    return tmp_path


def _draft(root: Path, *, tag: bool = True) -> None:
    path = root / "release-please-config.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["draft"] = True
    obj["force-tag-creation"] = tag
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_current_published_first_workflows_are_unmodified_by_guard() -> None:
    assert validate_cutover(ROOT) == []


def test_force_tag_creation_alone_does_not_enable_drafts(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    path = root / "release-please-config.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    config["force-tag-creation"] = True
    path.write_text(json.dumps(config), encoding="utf-8")
    assert validate_cutover(root) == []


def test_cutover_rejects_draft_without_immediate_tag_creation(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root, tag=False)
    assert any("force-tag-creation=true" in problem for problem in validate_cutover(root))


def test_cutover_rejects_active_autonomous_publishers_and_old_allowlist(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    errors = validate_cutover(root)
    assert any("legacy published-release mutation allowances" in e for e in errors)
    for filename in _PUBLISHERS:
        assert any(e.startswith(filename + ":") for e in errors)


def test_cutover_rejects_mixed_modes(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    config_path = root / "release-please-config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["packages"]["src-tauri"]["draft"] = False
    config_path.write_text(json.dumps(config), encoding="utf-8")
    assert any("no mixed-mode" in e for e in validate_cutover(root))


def test_cutover_rejects_rogue_release_and_tag_triggers(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    for filename in _PUBLISHERS:
        path = root / ".github" / "workflows" / filename
        path.write_text(
            (
                "on:\n  workflow_call:\n  release:\n    types: [published]\n"
                "  push:\n    tags: ['v*']\n"
            ),
            encoding="utf-8",
        )
    errors = validate_cutover(root)
    assert sum("remove autonomous release trigger" in e for e in errors) == len(_PUBLISHERS)
    assert sum("remove autonomous push trigger" in e for e in errors) == len(_PUBLISHERS)


@pytest.mark.parametrize(
    "trigger",
    [
        "push:",
        "push: {}",
        "push:\n    branches: [main]",
        "schedule:\n    - cron: '0 0 * * *'",
        "workflow_run:\n    workflows: [CI]\n    types: [completed]",
        "repository_dispatch:",
        "release:\n    types: [published]",
    ],
)
def test_cutover_rejects_any_autonomous_event(tmp_path: Path, trigger: str) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    path = root / ".github" / "workflows" / _PUBLISHERS[0]
    path.write_text(
        "on:\n  workflow_call:\n  workflow_dispatch:\n  pull_request:\n  " + trigger + "\n",
        encoding="utf-8",
    )
    assert any(f"{_PUBLISHERS[0]}: remove autonomous" in e for e in validate_cutover(root))


@pytest.mark.parametrize("filename", _PUBLISHERS)
def test_cutover_rejects_independent_manual_publisher_dispatch(
    tmp_path: Path, filename: str
) -> None:
    """The owner workflow must be the sole writer when draft cutover is active."""
    root = _fixture(tmp_path)
    _draft(root)
    for publisher in _PUBLISHERS:
        (root / ".github" / "workflows" / publisher).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    (root / ".github" / "workflows" / filename).write_text(
        "on:\n  workflow_call:\n  workflow_dispatch:\n",
        encoding="utf-8",
    )
    errors = validate_cutover(root, {"release_asset_mutations": []})
    assert any(
        error.startswith(f"{filename}:") and "workflow_dispatch" in error for error in errors
    )


def _ready_owner(root: Path) -> Path:
    """The future draft-first owner must preserve and queue release writes."""
    path = root / ".github" / "workflows" / "publish-release.yml"
    source = path.read_text(encoding="utf-8")
    assert source.count("  cancel-in-progress: false\n") == 1
    if "  queue: max\n" not in source:
        source = source.replace(
            "  cancel-in-progress: false\n",
            "  cancel-in-progress: false\n  queue: max\n",
        )
        path.write_text(source, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "run-specific-group",
        "cancel-running",
        "drop-pending",
        "remove-cancel",
        "remove-queue",
    ],
)
def test_draft_cutover_requires_serialized_non_lossy_owner(tmp_path: Path, mutation: str) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    path = _ready_owner(root)
    valid = path.read_text(encoding="utf-8")
    group = "publish-release-${{ github.repository }}"
    if mutation == "missing":
        changed = valid.replace(
            "concurrency:\n  group: " + group + "\n  cancel-in-progress: false\n  queue: max\n",
            "",
        )
    elif mutation == "run-specific-group":
        changed = valid.replace(
            group,
            "publish-release-${{ github.run_id }}",
        )
    elif mutation == "cancel-running":
        changed = valid.replace("cancel-in-progress: false", "cancel-in-progress: true")
    elif mutation == "drop-pending":
        changed = valid.replace("queue: max", "queue: single")
    elif mutation == "remove-cancel":
        changed = valid.replace("  cancel-in-progress: false\n", "")
    else:
        changed = valid.replace("  queue: max\n", "")
    assert changed != valid
    path.write_text(changed, encoding="utf-8")
    errors = validate_cutover(root, {"release_asset_mutations": []})
    assert any("owner concurrency" in error for error in errors)


def _safe_release_please_owner(root: Path) -> Path:
    """Model the future owner where Release Please cannot publish before staging."""
    path = root / ".github" / "workflows" / "publish-release.yml"
    original = path.read_text(encoding="utf-8")
    assert "skip-github-release: false" in original
    path.write_text(
        original.replace("skip-github-release: false", "skip-github-release: true"),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("setting", ["false", "'false'", "missing", "numeric-true"])
def test_draft_cutover_rejects_early_release_please_publication(
    tmp_path: Path, setting: str
) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    owner = _ready_owner(root)
    source = owner.read_text(encoding="utf-8")
    if setting == "missing":
        source = source.replace("          skip-github-release: false\n", "")
    elif setting == "'false'":
        source = source.replace("skip-github-release: false", "skip-github-release: 'false'")
    elif setting == "numeric-true":
        source = source.replace("skip-github-release: false", "skip-github-release: 1")
    owner.write_text(source, encoding="utf-8")
    for publisher in _PUBLISHERS:
        (root / ".github" / "workflows" / publisher).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    problems = validate_cutover(root, {"release_asset_mutations": []})
    assert any("Release Please" in problem and "publish" in problem for problem in problems)


def test_draft_cutover_accepts_owner_that_blocks_release_please_early_publish(
    tmp_path: Path,
) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    _ready_owner(root)
    _safe_release_please_owner(root)
    for publisher in _PUBLISHERS:
        (root / ".github" / "workflows" / publisher).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    _wire_owner_callees(root)
    assert validate_cutover(root, {"release_asset_mutations": []}) == []


def test_cutover_uses_supplied_policy_not_an_unrelated_disk_copy(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    _ready_owner(root)
    _safe_release_please_owner(root)
    for filename in _PUBLISHERS:
        (root / ".github" / "workflows" / filename).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    disk_policy = root / ".github" / "actions-policy.json"
    disk_policy.write_text(json.dumps({"release_asset_mutations": []}), encoding="utf-8")
    # This is the exact object passed to validate_repository by callers.
    assert any(
        "legacy published-release mutation allowances" in e
        for e in validate_cutover(root, {"release_asset_mutations": [{"issue": "#1179"}]})
    )
    disk_policy.write_text(
        json.dumps({"release_asset_mutations": [{"issue": "#1179"}]}), encoding="utf-8"
    )
    _wire_owner_callees(root)
    assert validate_cutover(root, {"release_asset_mutations": []}) == []


def test_cutover_can_check_the_necessary_post_migration_conditions(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    _ready_owner(root)
    _safe_release_please_owner(root)
    for filename in _PUBLISHERS:
        (root / ".github" / "workflows" / filename).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    (root / ".github" / "actions-policy.json").write_text(
        json.dumps({"release_asset_mutations": []}), encoding="utf-8"
    )
    _wire_owner_callees(root)
    assert validate_cutover(root) == []  # Necessary static conditions, NOT publish approval.


def test_invalid_workflow_fails_closed(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    (root / ".github" / "workflows" / _PUBLISHERS[0]).write_text(
        "name: missing events\n", encoding="utf-8"
    )
    assert any("missing workflow event mapping" in e for e in validate_cutover(root))


def test_safe_loader_exposes_github_on_keyword_as_bool() -> None:
    assert yaml.safe_load("on:\n  push:\n") == {True: {"push": None}}


@pytest.mark.parametrize(
    "event_map",
    [
        # A duplicate top-level on key must not hide an autonomous trigger.
        "on:\n  push:\n    tags: ['v*']\non:\n  workflow_call:\n",
        # A duplicate event nested in on must be rejected.
        "on:\n  workflow_call:\n  push:\n    tags: ['v*']\n  push:\n",
        # Quoted/unquoted on keys must not produce ambiguous triggers.
        "on:\n  workflow_call:\n'on':\n  workflow_call:\n",
    ],
)
def test_cutover_rejects_duplicate_workflow_event_keys(tmp_path: Path, event_map: str) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    filename = _PUBLISHERS[0]
    (root / ".github" / "workflows" / filename).write_text(event_map, encoding="utf-8")
    assert any(
        error.startswith(f"{filename}:") and "duplicate" in error
        for error in validate_cutover(root)
    )


def _wire_owner_callees(root: Path) -> None:
    owner = root / ".github" / "workflows" / "publish-release.yml"
    with owner.open("a", encoding="utf-8") as stream:
        for index, publisher in enumerate(_PUBLISHERS, 1):
            stream.write(f"  draft-family-{index}:\n    uses: ./.github/workflows/{publisher}\n")


def test_draft_cutover_rejects_owner_with_no_family_calls(tmp_path: Path) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    _ready_owner(root)
    _safe_release_please_owner(root)
    for publisher in _PUBLISHERS:
        (root / ".github" / "workflows" / publisher).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    assert any(
        "owner must call" in problem
        for problem in validate_cutover(root, {"release_asset_mutations": []})
    )


@pytest.mark.parametrize("drift", ["missing", "duplicate", "untrusted"])
def test_draft_cutover_rejects_incorrect_owner_family_calls(tmp_path: Path, drift: str) -> None:
    root = _fixture(tmp_path)
    _draft(root)
    _ready_owner(root)
    _safe_release_please_owner(root)
    for publisher in _PUBLISHERS:
        (root / ".github" / "workflows" / publisher).write_text(
            "on:\n  workflow_call:\n", encoding="utf-8"
        )
    _wire_owner_callees(root)
    owner = root / ".github" / "workflows" / "publish-release.yml"
    source = owner.read_text()
    target = f"./.github/workflows/{_PUBLISHERS[0]}"
    if drift == "missing":
        source = source.replace(f"uses: {target}", "uses: ./.github/workflows/ci.yml")
    elif drift == "duplicate":
        source += f"  duplicate-family:\n    uses: {target}\n"
    else:
        source = source.replace(f"uses: {target}", f"uses: other-org/repo/{_PUBLISHERS[0]}@main")
    owner.write_text(source)
    assert any(
        "owner must call" in problem
        for problem in validate_cutover(root, {"release_asset_mutations": []})
    )
