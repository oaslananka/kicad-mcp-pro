from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
    monkeypatch.setattr(module, "_check_desktop_backend_contract", lambda: [])
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


def test_release_preflight_tracks_tauri_bundle_version() -> None:
    module = _load_script("check_release_preflight.py")
    versions = module._collect_versions()

    expected = {
        "src-tauri/Cargo.toml",
        "src-tauri/tauri.conf.json",
        ".release-please-manifest.json src-tauri",
    }
    assert expected.issubset(versions)
    assert len({versions[source] for source in expected}) == 1


def test_desktop_launcher_is_release_coupled_and_runs_contract_tests() -> None:
    launcher = (ROOT / "src-tauri" / "src" / "lib.rs").read_text(encoding="utf-8")
    gui_ci = (ROOT / ".github" / "workflows" / "gui-ci.yml").read_text(encoding="utf-8")

    assert 'const DESKTOP_API_CONTRACT_VERSION: &str = "1.0.0";' in launcher
    assert 'env!("CARGO_PKG_VERSION")' in launcher
    assert "kicad-mcp-pro=={}" in launcher
    assert "kicad-mcp-pro>=3.11.0" not in launcher
    assert "kicad-mcp-pro@latest" not in launcher
    assert '"desktopCompatibility"' in launcher
    assert "run: cargo test --locked --lib" in gui_ci


def test_release_preflight_detects_desktop_backend_contract_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    python_dir = tmp_path / "src" / "kicad_mcp"
    tauri_dir = tmp_path / "src-tauri" / "src"
    python_dir.mkdir(parents=True)
    tauri_dir.mkdir(parents=True)
    (python_dir / "compatibility.py").write_text(
        'DESKTOP_API_CONTRACT_VERSION: Final = "1.0.1"\n'
        'DESKTOP_BACKEND_VERSION_POLICY: Final = "exact-release"\n',
        encoding="utf-8",
    )
    (tauri_dir / "lib.rs").write_text(
        'const DESKTOP_API_CONTRACT_VERSION: &str = "1.0.0";\n'
        'const DESKTOP_BACKEND_VERSION_POLICY: &str = "exact-release";\n'
        'format!("kicad-mcp-pro=={}", env!("CARGO_PKG_VERSION"));\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    errors = module._check_desktop_backend_contract()

    assert errors == ["desktop API contract drift detected: python=1.0.1, tauri=1.0.0"]


def test_release_preflight_rejects_non_exact_desktop_backend_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    python_dir = tmp_path / "src" / "kicad_mcp"
    tauri_dir = tmp_path / "src-tauri" / "src"
    python_dir.mkdir(parents=True)
    tauri_dir.mkdir(parents=True)
    (python_dir / "compatibility.py").write_text(
        'DESKTOP_API_CONTRACT_VERSION: Final = "1.0.0"\n'
        'DESKTOP_BACKEND_VERSION_POLICY: Final = "exact-release"\n',
        encoding="utf-8",
    )
    (tauri_dir / "lib.rs").write_text(
        'const DESKTOP_API_CONTRACT_VERSION: &str = "1.0.0";\n'
        'const DESKTOP_BACKEND_VERSION_POLICY: &str = "exact-release";\n'
        'const MIN_BACKEND_SPEC: &str = "kicad-mcp-pro>=3.11.0";\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)

    errors = module._check_desktop_backend_contract()

    assert errors == [
        "desktop launcher must derive an exact kicad-mcp-pro==<GUI version> spec "
        "from CARGO_PKG_VERSION"
    ]


def test_tauri_lockfile_is_tracked_and_workflows_use_locked_resolution() -> None:
    lockfile = ROOT / "src-tauri" / "Cargo.lock"
    ignored = {
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    gui_ci = (ROOT / ".github" / "workflows" / "gui-ci.yml").read_text(encoding="utf-8")
    gui_release = (ROOT / ".github" / "workflows" / "gui-release.yml").read_text(encoding="utf-8")

    assert lockfile.is_file()
    assert "src-tauri/Cargo.lock" not in ignored
    assert "run: cargo check --locked" in gui_ci
    assert "run: cargo metadata --locked --format-version 1 --no-deps" in gui_release
    assert "run: cargo tauri build ${{ matrix.args }} -- --locked" in gui_release


def test_gui_release_uses_exact_reviewed_tauri_cli_version() -> None:
    contract = dict(
        line.split("=", 1)
        for line in (ROOT / "scripts" / "dev-toolchain.env")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#")
    )
    version = contract["TAURI_CLI_VERSION"]
    gui_release = (ROOT / ".github" / "workflows" / "gui-release.yml").read_text(encoding="utf-8")

    assert version.count(".") == 2
    assert f'cargo install tauri-cli --version "{version}" --locked' in gui_release


def test_release_preflight_rejects_tauri_root_version_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    tauri_dir = tmp_path / "src-tauri"
    tauri_dir.mkdir()
    (tauri_dir / "Cargo.toml").write_text(
        '[package]\nname = "kicad-mcp-pro"\nversion = "3.30.1"\n',
        encoding="utf-8",
    )
    (tauri_dir / "Cargo.lock").write_text(
        'version = 3\n\n[[package]]\nname = "kicad-mcp-pro"\nversion = "3.30.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stderr=""),
    )

    errors = module._check_tauri_lockfile()

    assert errors == [
        "src-tauri/Cargo.lock root package version does not match Cargo.toml: "
        "lock=3.30.0, manifest=3.30.1"
    ]


def test_release_preflight_rejects_stale_tauri_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script("check_release_preflight.py")
    tauri_dir = tmp_path / "src-tauri"
    tauri_dir.mkdir()
    (tauri_dir / "Cargo.toml").write_text(
        '[package]\nname = "fixture"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    (tauri_dir / "Cargo.lock").write_text(
        'version = 3\n\n[[package]]\nname = "fixture"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module.shutil, "which", lambda executable: "/usr/bin/cargo")
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=101,
            stderr="the lock file needs to be updated",
        ),
    )

    errors = module._check_tauri_lockfile()

    assert errors == [
        "src-tauri/Cargo.lock is stale; run cargo metadata --locked after updating Cargo.toml"
    ]


def test_release_validation_runs_for_tauri_dependency_changes() -> None:
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert '- "src-tauri/Cargo.toml"' in workflow
    assert '- "src-tauri/Cargo.lock"' in workflow
    assert '- "scripts/check_release_preflight.py"' in workflow


def test_dependabot_covers_repository_dependency_ecosystems_and_lockfiles() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = config["updates"]
    ecosystems = {entry["package-ecosystem"] for entry in updates}

    assert {"uv", "npm", "github-actions", "docker", "docker-compose", "cargo"} <= ecosystems
    assert (
        next(entry for entry in updates if entry["package-ecosystem"] == "uv")["directory"] == "/"
    )
    assert (
        next(entry for entry in updates if entry["package-ecosystem"] == "cargo")["directory"]
        == "/src-tauri"
    )

    npm_directories = set(
        next(entry for entry in updates if entry["package-ecosystem"] == "npm")["directories"]
    )
    assert "/" in npm_directories
    assert "/integrations/chatgpt-app/apps-sdk" in npm_directories

    policy = (ROOT / "docs" / "development" / "dependency-management.md").read_text(
        encoding="utf-8"
    )
    for lockfile in ("uv.lock", "pnpm-lock.yaml", "package-lock.json", "src-tauri/Cargo.lock"):
        assert lockfile in policy


def test_dependabot_groups_routine_updates_without_grouping_major_versions() -> None:
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    updates = {entry["package-ecosystem"]: entry for entry in config["updates"]}

    expected_version_groups = {
        "uv": ("python-minor-patch", {"minor", "patch"}),
        "npm": ("npm-minor-patch", {"minor", "patch"}),
        "github-actions": ("actions-minor-patch", {"minor", "patch"}),
        "docker": ("containers-patch", {"patch"}),
        "docker-compose": ("compose-minor-patch", {"minor", "patch"}),
        "cargo": ("cargo-minor-patch", {"minor", "patch"}),
    }
    for ecosystem, (group_name, update_types) in expected_version_groups.items():
        group = updates[ecosystem]["groups"][group_name]
        assert group["applies-to"] == "version-updates"
        assert group["patterns"] == ["*"]
        assert set(group["update-types"]) == update_types
        assert "major" not in group["update-types"]

    for ecosystem, group_name in {
        "uv": "python-security",
        "npm": "npm-security",
        "cargo": "cargo-security",
    }.items():
        group = updates[ecosystem]["groups"][group_name]
        assert group["applies-to"] == "security-updates"
        assert group["patterns"] == ["*"]


def test_mergify_only_autoqueues_safe_grouped_dependabot_updates() -> None:
    config = yaml.safe_load((ROOT / ".mergify.yml").read_text(encoding="utf-8"))

    assert "merge_protections" not in config
    assert "merge_protections_settings" not in config
    assert config["merge_queue"] == {"mode": "serial", "max_parallel_checks": 1}

    assert len(config["queue_rules"]) == 1
    queue = config["queue_rules"][0]
    assert queue["name"] == "safe-dependencies"
    assert queue["batch_size"] == 1
    assert queue["merge_method"] == "squash"
    assert queue["branch_protection_injection_mode"] == "queue"
    assert queue["max_checks_retries"] == 0

    required_conditions = {
        "base = main",
        "author = dependabot[bot]",
        "-draft",
        "dependabot-update-type != version-update:semver-major",
    }
    assert required_conditions <= set(queue["queue_conditions"])

    assert len(config["pull_request_rules"]) == 1
    rule = config["pull_request_rules"][0]
    assert rule["actions"] == {"queue": {"name": "safe-dependencies"}}
    assert required_conditions <= set(rule["conditions"])

    head_conditions = [
        condition for condition in rule["conditions"] if condition.startswith("head ~= ")
    ]
    assert len(head_conditions) == 1
    head_condition = head_conditions[0]
    for group_name in (
        "python-minor-patch",
        "npm-minor-patch",
        "actions-minor-patch",
        "containers-patch",
        "compose-minor-patch",
        "cargo-minor-patch",
    ):
        assert group_name in head_condition
    assert "security" not in head_condition


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
    queue = next(rule for rule in mergify["queue_rules"] if rule["name"] == "safe-dependencies")
    explicit_check_conditions = {
        condition.removeprefix("check-success = ")
        for condition in queue["merge_conditions"]
        if condition.startswith("check-success = ")
    }

    assert explicit_check_conditions == required_contexts


def test_release_preflight_rejects_missing_tauri_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("check_release_preflight.py")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_project_version", lambda: "3.30.0")
    monkeypatch.setattr(module, "_check_versions", lambda: [])
    monkeypatch.setattr(module, "_check_desktop_backend_contract", lambda: [])
    monkeypatch.setattr(module, "_check_protocol_schema_version", lambda: [])
    monkeypatch.setattr(module, "_check_citation", lambda version: [])
    monkeypatch.setattr(module, "_check_changelog", lambda version: [])
    monkeypatch.setattr(module, "validate_compatibility_matrix", lambda: [])

    assert module.main() == 1
    assert "src-tauri/Cargo.lock is missing" in capsys.readouterr().err


def test_release_please_tauri_extra_file_is_package_relative() -> None:
    config = json.loads((ROOT / "release-please-config.json").read_text(encoding="utf-8"))
    extra_files = config["packages"]["src-tauri"]["extra-files"]

    assert {
        "type": "json",
        "path": "tauri.conf.json",
        "jsonpath": "$.version",
    } in extra_files
    assert all(entry["path"] != "src-tauri/tauri.conf.json" for entry in extra_files)


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
    assert commands == [["actionlint"]]


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
