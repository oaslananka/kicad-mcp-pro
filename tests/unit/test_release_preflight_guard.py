from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str) -> object:
    script = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), script)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(script.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(script.parent))
    return module


def test_release_preflight_scans_only_current_changelog_section(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    monkeypatch.delenv("GITHUB_HEAD_REF", raising=False)
    monkeypatch.delenv("RELEASE_PLEASE_GENERATED_CHANGELOG", raising=False)
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        """
## [Unreleased]

## [3.1.8]

* fix current release issue

## [2.0.2]

* Bump version to 2.0.2 and update changelog
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)

    assert module._check_changelog("3.1.8") == []

    changelog.write_text(
        """
## [Unreleased]

## [3.1.8]

* Bump version to 2.0.2 and update changelog

## [2.0.2]

* legacy history
""".lstrip(),
        encoding="utf-8",
    )

    errors = module._check_changelog("3.1.8")
    assert errors
    assert "current release section" in errors[0]


def test_release_preflight_rejects_unmanaged_stale_citation_date(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("check_release_preflight.py")
    (tmp_path / "CITATION.cff").write_text(
        """
version: "3.26.0" # x-release-please-version
date-released: "2026-07-10"
""".lstrip(),
        encoding="utf-8",
    )
    (tmp_path / "CHANGELOG.md").write_text(
        "## [3.26.0](https://example.test/compare) (2026-07-21)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_project_version", lambda: "3.26.0")
    monkeypatch.setattr(module, "_check_versions", lambda: [])
    monkeypatch.setattr(module, "_check_protocol_schema_version", lambda: [])
    monkeypatch.setattr(module, "_check_changelog", lambda version: [])
    monkeypatch.setattr(module, "validate_compatibility_matrix", lambda: [])

    assert module.main() == 1
    stderr = capsys.readouterr().err
    assert "CITATION.cff date-released" in stderr
    assert "x-release-please-date" in stderr


def test_repository_citation_release_date_is_release_please_managed() -> None:
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    date_line = next(line for line in citation.splitlines() if line.startswith("date-released:"))

    assert "x-release-please-date" in date_line


def test_dependabot_covers_repository_dependency_ecosystems_and_lockfiles() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]
    ecosystems = {entry["package-ecosystem"] for entry in updates}

    assert {"uv", "npm", "github-actions", "docker", "docker-compose"} <= ecosystems
    assert (
        next(entry for entry in updates if entry["package-ecosystem"] == "uv")["directory"] == "/"
    )

    npm_directories = {
        entry.get("directory") for entry in updates if entry["package-ecosystem"] == "npm"
    }
    assert "/" in npm_directories
    # Only security updates belong to Dependabot; normal versions are Renovate-owned.
    assert "/integrations/chatgpt-app/apps-sdk" in npm_directories

    policy = (ROOT / "docs" / "development" / "dependency-management.md").read_text(
        encoding="utf-8"
    )
    for lockfile in ("uv.lock", "pnpm-lock.yaml", "package-lock.json"):
        assert lockfile in policy


def test_dependabot_staggers_version_updates_and_bounds_automation_backlog() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]

    expected_windows = {
        ("uv", "/"): ("monday", "04:00"),
        ("npm", "/"): ("monday", "12:00"),
        ("npm", "/integrations/chatgpt-app/apps-sdk"): ("tuesday", "04:00"),
        ("npm", "/packages/kicad-fixtures"): ("tuesday", "12:00"),
        ("npm", "/packages/mcp-npm"): ("wednesday", "04:00"),
        ("github-actions", "/"): ("thursday", "04:00"),
        ("docker", "/"): ("friday", "04:00"),
        ("docker-compose", "/"): ("friday", "12:00"),
    }
    actual_windows = {
        (entry["package-ecosystem"], entry["directory"]): (
            entry["schedule"]["day"],
            entry["schedule"]["time"],
        )
        for entry in updates
    }

    assert actual_windows == expected_windows
    assert len(set(actual_windows.values())) == len(actual_windows)

    for entry in updates:
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["timezone"] == "Europe/Istanbul"
        if (entry["package-ecosystem"], entry["directory"]) == (
            "npm",
            "/integrations/chatgpt-app/apps-sdk",
        ):
            assert entry["open-pull-requests-limit"] == 0
        else:
            assert entry["open-pull-requests-limit"] == 2
        assert entry["cooldown"] == {"default-days": 5}


def test_dependabot_npm_updates_respect_package_manager_boundaries() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    npm_updates = [entry for entry in config["updates"] if entry["package-ecosystem"] == "npm"]

    expected_directories = {
        "/": ("npm-root-minor-patch", "npm-root-major", "npm-root-security"),
        "/integrations/chatgpt-app/apps-sdk": (
            "npm-chatgpt-app-minor-patch",
            "npm-chatgpt-app-major",
            "npm-chatgpt-app-security",
        ),
        "/packages/kicad-fixtures": (
            "npm-fixtures-minor-patch",
            "npm-fixtures-major",
            "npm-fixtures-security",
        ),
        "/packages/mcp-npm": (
            "npm-wrapper-minor-patch",
            "npm-wrapper-major",
            "npm-wrapper-security",
        ),
    }
    assert {entry.get("directory") for entry in npm_updates} == set(expected_directories)
    assert all("directories" not in entry for entry in npm_updates)

    for entry in npm_updates:
        directory = entry["directory"]
        routine_name, major_name, security_name = expected_directories[directory]

        routine_group = entry["groups"][routine_name]
        assert routine_group["applies-to"] == "version-updates"
        assert routine_group["patterns"] == ["*"]
        assert set(routine_group["update-types"]) == {"minor", "patch"}

        major_group = entry["groups"][major_name]
        assert major_group["applies-to"] == "version-updates"
        assert major_group["patterns"] == ["*"]
        assert major_group["update-types"] == ["major"]

        security_group = entry["groups"][security_name]
        assert security_group["applies-to"] == "security-updates"
        assert security_group["patterns"] == ["*"]


def test_dependabot_docker_defers_only_incompatible_python_runtime_line() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    docker = next(
        item
        for item in config["updates"]
        if item["package-ecosystem"] == "docker" and item["directory"] == "/"
    )
    # Python 3.14 -> 3.15 is a Python feature-line migration, but looks like
    # SemVer minor to Dependabot. Exclude a version range rather than semver-major.
    assert docker["ignore"] == [{"dependency-name": "python", "versions": [">= 3.15.0"]}]
    from packaging.specifiers import SpecifierSet

    ignored = SpecifierSet(docker["ignore"][0]["versions"][0])
    assert "3.14.10" not in ignored  # Safe 3.14 patch upgrades are still eligible.
    assert "3.15.0" in ignored
    assert "3.16.0" in ignored
    assert docker["groups"]["containers-patch"]["update-types"] == ["patch"]


def test_dependabot_groups_routine_and_major_updates_separately() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = {
        entry["package-ecosystem"]: entry
        for entry in config["updates"]
        if entry["package-ecosystem"] != "npm"
    }

    expected_groups = {
        "uv": (
            ("python-minor-patch", {"minor", "patch"}),
            ("python-major", {"major"}),
        ),
        "github-actions": (
            ("actions-minor-patch", {"minor", "patch"}),
            ("actions-major", {"major"}),
        ),
        "docker": (
            ("containers-patch", {"patch"}),
            ("containers-manual", {"minor", "major"}),
        ),
        "docker-compose": (
            ("compose-patch", {"patch"}),
            ("compose-manual", {"minor", "major"}),
        ),
    }
    for ecosystem, groups in expected_groups.items():
        for group_name, update_types in groups:
            group = updates[ecosystem]["groups"][group_name]
            assert group["applies-to"] == "version-updates"
            assert group["patterns"] == ["*"]
            assert set(group["update-types"]) == update_types

    for ecosystem, group_name in {
        "uv": "python-security",
    }.items():
        group = updates[ecosystem]["groups"][group_name]
        assert group["applies-to"] == "security-updates"
        assert group["patterns"] == ["*"]


def test_mergify_only_autoqueues_safe_grouped_dependabot_updates() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))

    assert "merge_protections" not in config
    assert "merge_protections_settings" not in config
    assert config["merge_queue"] == {"mode": "serial", "max_parallel_checks": 1}

    assert [rule["name"] for rule in config["queue_rules"]] == [
        "safe-dependencies",
        "renovate-pilot-safe",
        "maintainer",
    ]
    queue = config["queue_rules"][0]
    assert queue["batch_size"] == 1
    assert queue["merge_method"] == "squash"
    assert queue["branch_protection_injection_mode"] == "queue"
    assert queue["max_checks_retries"] == 0

    required_conditions = {
        "base = main",
        "author = dependabot[bot]",
        "-draft",
        "dependabot-update-type != version-update:semver-major",
        "#review-threads-unresolved = 0",
    }
    queue_strings = {
        condition for condition in queue["queue_conditions"] if isinstance(condition, str)
    }
    assert required_conditions <= queue_strings

    assert len(config["pull_request_rules"]) == 2
    rule = config["pull_request_rules"][0]
    assert rule["actions"] == {"queue": {"name": "safe-dependencies"}}
    assert required_conditions <= set(rule["conditions"])

    head_conditions = [
        condition for condition in rule["conditions"] if condition.startswith("head ~= ")
    ]
    assert len(head_conditions) == 1
    head_condition = head_conditions[0]

    auto_groups = (
        "python-minor-patch",
        "python-security",
        "npm-root-minor-patch",
        "npm-root-security",
        "npm-chatgpt-app-minor-patch",
        "npm-chatgpt-app-security",
        "npm-fixtures-minor-patch",
        "npm-fixtures-security",
        "npm-wrapper-minor-patch",
        "npm-wrapper-security",
        "actions-minor-patch",
        "containers-patch",
        "compose-patch",
        "cargo-minor-patch",
        "cargo-security",
    )
    for group_name in auto_groups:
        assert group_name in head_condition

    for manual_group in (
        "python-major",
        "npm-root-major",
        "npm-chatgpt-app-major",
        "npm-fixtures-major",
        "npm-wrapper-major",
        "actions-major",
        "containers-manual",
        "compose-manual",
        "cargo-major",
    ):
        assert manual_group not in head_condition


def test_mergify_merge_conditions_mirror_repository_ruleset_required_checks() -> None:
    ruleset = json.loads((ROOT / ".github" / "rulesets" / "main.json").read_text(encoding="utf-8"))
    required_contexts = {
        check["context"]
        for rule in ruleset["rules"]
        if rule["type"] == "required_status_checks"
        for check in rule["parameters"]["required_status_checks"]
    }
    assert required_contexts

    mergify = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    for name in ("safe-dependencies", "renovate-pilot-safe", "maintainer"):
        queue = next(rule for rule in mergify["queue_rules"] if rule["name"] == name)
        explicit_check_conditions = {
            condition.removeprefix("check-success = ")
            for condition in queue["merge_conditions"]
            if isinstance(condition, str) and condition.startswith("check-success = ")
        }
        assert explicit_check_conditions == required_contexts, name
        assert not any(isinstance(condition, dict) for condition in queue["merge_conditions"]), name


def test_mergify_uses_in_place_checks_with_strict_main_ruleset() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))

    assert config["merge_queue"]["max_parallel_checks"] == 1
    for queue in config["queue_rules"]:
        assert queue["batch_size"] == 1
        assert queue["queue_conditions"] == queue["merge_conditions"]


def test_mergify_maintainer_queue_is_command_only_and_write_restricted() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))
    queue = next(rule for rule in config["queue_rules"] if rule["name"] == "maintainer")

    assert queue["merge_method"] == "squash"
    assert queue["branch_protection_injection_mode"] == "queue"
    assert queue["max_checks_retries"] == 0
    conditions = {
        condition for condition in queue["queue_conditions"] if isinstance(condition, str)
    }
    assert {
        "base = main",
        "-draft",
        "author != dependabot[bot]",
        "#review-threads-unresolved = 0",
    } <= conditions

    # No pull_request_rule may queue into the maintainer rule automatically; a person with
    # write access has to issue the queue command.
    for rule in config["pull_request_rules"]:
        assert rule["actions"].get("queue", {}).get("name") != "maintainer"
    assert config["commands_restrictions"] == {
        "queue": {"conditions": ["sender-permission >= write"]}
    }


def test_release_preflight_skips_release_please_generated_changelog_noise(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        """
## [Unreleased]

## [3.1.8]

* Bump version to 2.0.2 and update changelog
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setenv("RELEASE_PLEASE_GENERATED_CHANGELOG", "true")

    assert module._check_changelog("3.1.8") == []


def test_no_pcbnew_guard_detects_imports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("check_no_pcbnew.py")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    good = src_dir / "good.py"
    bad = src_dir / "bad.py"
    good.write_text('PCBNEW_TEXT = "import pcbnew in docs only"\n', encoding="utf-8")
    bad.write_text("import pcbnew\npcbnew.LoadBoard('board.kicad_pcb')\n", encoding="utf-8")

    monkeypatch.setattr(module, "SCAN_DIRS", (src_dir,))

    assert module._violations(good) == []
    assert module.main() == 1


def test_no_pcbnew_guard_honors_matrix_allowlist(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_no_pcbnew.py")
    matrix = tmp_path / "compatibility.yaml"
    matrix.write_text(
        """
kicadIpcReadiness:
  directPcbnewImports:
    allowedPaths:
      - allowed/**
""".lstrip(),
        encoding="utf-8",
    )
    allowed_file = tmp_path / "allowed" / "fixture.py"
    blocked_file = tmp_path / "src" / "blocked.py"
    allowed_file.parent.mkdir()
    blocked_file.parent.mkdir()
    allowed_file.write_text("import pcbnew\n", encoding="utf-8")
    blocked_file.write_text("import pcbnew\n", encoding="utf-8")

    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "MATRIX_PATH", matrix)
    monkeypatch.setattr(module, "SCAN_DIRS", (tmp_path,))

    assert module._python_files() == [blocked_file]
    assert module.main() == 1


def test_workflow_lint_uses_locked_actionlint_binary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_workflows.py")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "example.yml").write_text(
        "name: Example\non: workflow_dispatch\njobs: {}\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_run", commands.append)
    monkeypatch.setattr(sys, "argv", ["check_workflows.py", "--actionlint"])

    module.main()

    assert module.ACTIONLINT_COMMAND == ["actionlint"]
    assert commands == [
        ["actionlint", "-ignore", 'unexpected key "queue" for "concurrency" section']
    ]


def test_workflow_lint_rejects_unapproved_queue_even_with_legacy_actionlint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script("check_workflows.py")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "unrelated.yml").write_text(
        "name: Test\nconcurrency:\n  group: other\n  queue: max\njobs: {}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", ["check_workflows.py", "--actionlint"])
    with pytest.raises(ValueError, match="unapproved concurrency queue"):
        module.main()


def test_workflow_lint_has_no_workspace_specific_fallback() -> None:
    module = _load_script("check_workflows.py")

    assert not hasattr(module, "WORKSPACE_ACTIONLINT_COMMAND")
    assert "kicadstudio" not in Path(__file__).resolve().parents[2].joinpath(
        "scripts", "check_workflows.py"
    ).read_text(encoding="utf-8")


def test_workflow_lint_resolves_windows_command_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_script("check_workflows.py")
    monkeypatch.setattr(module.shutil, "which", lambda name: f"C:/tools/{name}.CMD")

    assert module._resolve_command(["corepack", "pnpm", "--version"]) == [
        "C:/tools/corepack.CMD",
        "pnpm",
        "--version",
    ]


def test_http_only_release_family_keeps_python_npm_without_tauri() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert "src-tauri" not in config["packages"]
    assert "src-tauri" not in manifest
    assert set(config["packages"]) >= {".", "packages/mcp-npm"}
    assert "kicad-mcp-gui" not in config["plugins"][0]["components"]
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "src-tauri" not in workflow
