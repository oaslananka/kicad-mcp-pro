from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_renovate_updates_cargo_manifests_and_lockfiles() -> None:
    config = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))

    assert "cargo" in config["enabledManagers"]
    assert config["lockFileMaintenance"]["enabled"] is True


def test_release_preflight_rejects_missing_tauri_lockfile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    module = _load_script("check_release_preflight.py")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "_project_version", lambda: "3.30.0")
    monkeypatch.setattr(module, "_check_versions", lambda: [])
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
