from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_checker() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_patch_coverage", ROOT / "scripts" / "check_patch_coverage.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_parse_changed_lines_reads_added_target_lines_only() -> None:
    checker = _load_checker()
    diff = """diff --git a/src/kicad_mcp/a.py b/src/kicad_mcp/a.py
--- a/src/kicad_mcp/a.py
+++ b/src/kicad_mcp/a.py
@@ -10,2 +10,4 @@
 old
+new
 keep
+more
@@ -30 +31,0 @@
-deleted
diff --git a/src/kicad_mcp/b.py b/src/kicad_mcp/b.py
new file mode 100644
--- /dev/null
+++ b/src/kicad_mcp/b.py
@@ -0,0 +1,2 @@
+one
+two
"""

    assert checker.parse_changed_lines(diff) == {
        "src/kicad_mcp/a.py": {11, 13},
        "src/kicad_mcp/b.py": {1, 2},
    }


def test_read_coverage_json_returns_executable_line_hits(tmp_path: Path) -> None:
    checker = _load_checker()
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        '{"files":{"src/kicad_mcp/a.py":{"executed_lines":[10],"missing_lines":[11]}}}',
        encoding="utf-8",
    )

    assert checker.read_coverage_json(coverage) == {"src/kicad_mcp/a.py": {10: 1, 11: 0}}


def test_measure_patch_coverage_ignores_non_executable_changed_lines() -> None:
    checker = _load_checker()
    coverage = {"src/kicad_mcp/a.py": {10: 1, 11: 0, 13: 1}}
    changed = {"src/kicad_mcp/a.py": {10, 11, 12}}

    result = checker.measure_patch_coverage(coverage, changed)

    assert result.covered == 1
    assert result.total == 2
    assert result.percent == pytest.approx(50.0)
    assert result.uncovered == ("src/kicad_mcp/a.py:11",)


def test_measure_patch_coverage_passes_when_no_coverable_lines_changed() -> None:
    checker = _load_checker()

    result = checker.measure_patch_coverage(
        {"src/kicad_mcp/a.py": {10: 1}},
        {"src/kicad_mcp/a.py": {20, 21}},
    )

    assert result.covered == 0
    assert result.total == 0
    assert result.percent == pytest.approx(100.0)
    assert result.uncovered == ()


def test_check_threshold_fails_below_minimum() -> None:
    checker = _load_checker()
    result = checker.PatchCoverage(covered=8, total=10, uncovered=("src/kicad_mcp/a.py:11",))

    assert checker.check_threshold(result, 90.0) is False
    assert checker.check_threshold(result, 80.0) is True


def test_main_fails_when_changed_executable_lines_are_below_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _load_checker()
    coverage = tmp_path / "coverage.json"
    coverage.write_text(
        '{"files":{"src/kicad_mcp/a.py":{"executed_lines":[10],"missing_lines":[11]}}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(checker, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        checker,
        "_git_diff",
        lambda: "+++ b/src/kicad_mcp/a.py\n@@ -10,0 +11 @@\n+changed\n",
    )

    result = checker.main(
        [
            "--coverage-file",
            "coverage.json",
            "--min-percent",
            "90",
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "0.00% (0/1 executable changed lines; required 90.00%)" in captured.out
    assert "src/kicad_mcp/a.py:11" in captured.err


def test_git_diff_uses_synthetic_pull_request_base_without_cli_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = _load_checker()
    captured: list[str] = []

    class Completed:
        stdout = "diff-output"

    def fake_run(command: list[str], **_kwargs: object) -> Completed:
        captured.extend(command)
        return Completed()

    monkeypatch.setattr(checker.subprocess, "run", fake_run)

    assert checker._git_diff() == "diff-output"
    assert captured == [
        "git",
        "diff",
        "--unified=0",
        "--diff-filter=ACMR",
        "HEAD^1...HEAD",
        "--",
        "src/kicad_mcp",
    ]


def test_main_rejects_noncanonical_coverage_file_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _load_checker()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "coverage.json"
    outside.write_text('{"files":{}}', encoding="utf-8")
    monkeypatch.setattr(checker, "REPO_ROOT", repo_root)
    monkeypatch.setattr(checker, "_git_diff", lambda: "")

    result = checker.main(
        [
            "--coverage-file",
            str(outside),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "repository-local coverage.json" in captured.err


def test_main_rejects_coverage_symlink_escaping_repository(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checker = _load_checker()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text('{"files":{}}', encoding="utf-8")
    (repo_root / "coverage.json").symlink_to(outside)
    monkeypatch.setattr(checker, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        checker,
        "_git_diff",
        lambda: pytest.fail("git diff must not run for an escaping coverage file"),
    )

    result = checker.main(
        [
            "--coverage-file",
            "coverage.json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert "outside repository root" in captured.err
