from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from scripts import hook_pre_push
from scripts.hook_pre_push import Check, build_plan


def _commands(plan: list[Check]) -> list[list[str]]:
    return [check.command for check in plan]


def _names(plan: list[Check]) -> list[str]:
    return [check.name for check in plan]


def test_python_change_gets_scoped_quality_and_matching_tests(tmp_path: Path) -> None:
    source = tmp_path / "src" / "kicad_mcp" / "widgets.py"
    unit = tmp_path / "tests" / "unit" / "test_widgets.py"
    source.parent.mkdir(parents=True)
    unit.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    unit.write_text("def test_value(): pass\n", encoding="utf-8")

    plan = build_plan(["src/kicad_mcp/widgets.py"], root=tmp_path)
    names = _names(plan)
    commands = _commands(plan)

    assert names[:3] == ["ruff-format", "ruff-lint", "mypy-changed"]
    assert "targeted-tests" in names
    assert [
        commands[0][0],
        "-m",
        "pytest",
        "tests/unit/test_widgets.py",
        "-q",
    ] in commands
    assert not any("run_pytest.py" in " ".join(command) for command in commands)


def test_workflow_change_only_adds_workflow_checks(tmp_path: Path) -> None:
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: CI\n", encoding="utf-8")

    plan = build_plan([".github/workflows/ci.yml"], root=tmp_path)

    assert _names(plan) == ["workflow-policy", "actionlint", "zizmor"]


def test_web_and_tauri_checks_are_pre_push_only_and_conditional(tmp_path: Path) -> None:
    web = tmp_path / "src" / "kicad_mcp" / "web" / "dashboard.py"
    tauri = tmp_path / "src-tauri" / "src" / "main.rs"
    web.parent.mkdir(parents=True)
    tauri.parent.mkdir(parents=True)
    web.write_text("VALUE = 1\n", encoding="utf-8")
    tauri.write_text("fn main() {}\n", encoding="utf-8")

    plan = build_plan(
        ["src/kicad_mcp/web/dashboard.py", "src-tauri/src/main.rs"],
        root=tmp_path,
    )

    assert "web-route-tests" in _names(plan)
    assert "tauri-cargo-check" in _names(plan)


def test_documentation_only_change_has_no_python_or_full_suite(tmp_path: Path) -> None:
    doc = tmp_path / "docs" / "notes.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("# Notes\n", encoding="utf-8")

    plan = build_plan(["docs/notes.md"], root=tmp_path)

    assert plan == []


def test_changed_files_uses_pre_commit_push_range(monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_git_output(arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[0] == "diff":
            return "src/kicad_mcp/server.py\nREADME.md"
        raise AssertionError(arguments)

    monkeypatch.setenv("PRE_COMMIT_FROM_REF", "a" * 40)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "b" * 40)
    monkeypatch.setattr(hook_pre_push, "_git_output", fake_git_output)

    assert hook_pre_push.changed_files(None) == ["src/kicad_mcp/server.py", "README.md"]
    assert calls == [["diff", "--name-only", "--diff-filter=ACMRTUXB", f"{'a' * 40}..{'b' * 40}"]]


def test_new_branch_falls_back_to_main_merge_base(monkeypatch: MonkeyPatch) -> None:
    calls: list[list[str]] = []

    def fake_git_output(arguments: list[str]) -> str:
        calls.append(arguments)
        if arguments[:2] == ["merge-base", "origin/main"]:
            return "c" * 40
        if arguments[0] == "diff":
            return "package.json"
        raise AssertionError(arguments)

    monkeypatch.setenv("PRE_COMMIT_FROM_REF", hook_pre_push.ZERO_SHA)
    monkeypatch.setenv("PRE_COMMIT_TO_REF", "d" * 40)
    monkeypatch.delenv("PRE_PUSH_BASE", raising=False)
    monkeypatch.setattr(hook_pre_push, "_git_output", fake_git_output)

    assert hook_pre_push.changed_files(None) == ["package.json"]
    assert calls == [
        ["merge-base", "origin/main", "d" * 40],
        ["diff", "--name-only", "--diff-filter=ACMRTUXB", f"{'c' * 40}..{'d' * 40}"],
    ]


def test_canonical_helper_changes_select_architecture_guard(tmp_path: Path) -> None:
    changed_files = [
        "src/kicad_mcp/pcb/geometry.py",
        "src/kicad_mcp/validation/drc_runner.py",
    ]
    for relative_path in changed_files:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")

    plan = build_plan(changed_files, root=tmp_path)

    assert "architecture-boundaries" in _names(plan)
