from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

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
