"""Run change-scoped checks for the local pre-push hook.

The full repository suite belongs to CI. This hook keeps local pushes responsive
by selecting deterministic checks from the files that are actually being pushed.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parents[1]
ZERO_SHA = "0" * 40
MAX_TARGET_TEST_FILES = 12
_SAFE_GIT_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/@+,-]{0,254}")
_GIT_OBJECT_ID = re.compile(r"[0-9a-fA-F]{40,64}")


@dataclass(frozen=True)
class Check:
    """One named pre-push command."""

    name: str
    command: list[str]


def _is_under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(f"{prefix}/")


def _existing(paths: list[str], root: Path) -> list[str]:
    return sorted({path for path in paths if (root / path).is_file()})


def _matching_unit_tests(source_files: list[str], root: Path) -> list[str]:
    tests_root = root / "tests" / "unit"
    if not tests_root.is_dir():
        return []

    selected: set[str] = set()
    for source in source_files:
        stem = Path(source).stem
        if stem == "__init__":
            continue
        for candidate in tests_root.glob(f"test_*{stem}*.py"):
            selected.add(candidate.relative_to(root).as_posix())

    return sorted(selected)[:MAX_TARGET_TEST_FILES]


def build_plan(changed_files: list[str], *, root: Path = ROOT) -> list[Check]:
    """Return deterministic checks for the supplied repository-relative paths."""
    changed = _existing(changed_files, root)
    checks: list[Check] = []

    python_files = [
        path
        for path in changed
        if path.endswith(".py")
        and any(_is_under(path, prefix) for prefix in ("src", "tests", "scripts"))
    ]
    source_python = [path for path in python_files if _is_under(path, "src/kicad_mcp")]

    if python_files:
        checks.extend(
            [
                Check(
                    "ruff-format",
                    [sys.executable, "-m", "ruff", "format", "--check", *python_files],
                ),
                Check(
                    "ruff-lint",
                    [sys.executable, "-m", "ruff", "check", *python_files],
                ),
            ]
        )

    if source_python:
        checks.append(
            Check(
                "mypy-changed",
                [sys.executable, "-m", "mypy", *source_python],
            )
        )

    web_changed = any(
        _is_under(path, "src/kicad_mcp/web")
        or path in {"tests/unit/test_web_routes.py", "tests/unit/test_web_routes_step3.py"}
        for path in changed
    )

    explicit_unit_tests = [
        path
        for path in changed
        if _is_under(path, "tests/unit") and Path(path).name.startswith("test_")
    ]
    inferred_unit_tests = _matching_unit_tests(source_python, root)
    targeted_tests = sorted(set(explicit_unit_tests) | set(inferred_unit_tests))
    if web_changed:
        targeted_tests = [
            path
            for path in targeted_tests
            if path not in {"tests/unit/test_web_routes.py", "tests/unit/test_web_routes_step3.py"}
        ]
    if targeted_tests:
        checks.append(
            Check(
                "targeted-tests",
                [sys.executable, "-m", "pytest", *targeted_tests, "-q"],
            )
        )

    architecture_changed = any(
        _is_under(path, prefix)
        for path in changed
        for prefix in (
            "src/kicad_mcp/pcb",
            "src/kicad_mcp/schematic",
            "src/kicad_mcp/tools",
            "src/kicad_mcp/validation",
            "scripts/check_architecture_boundaries.py",
            "tests/unit/test_architecture_boundaries.py",
            "tests/unit/test_shared_helper_architecture.py",
        )
    )
    if architecture_changed:
        checks.append(
            Check(
                "architecture-boundaries",
                [sys.executable, "scripts/check_architecture_boundaries.py"],
            )
        )

    tool_surface_changed = any(
        _is_under(path, prefix)
        for path in changed
        for prefix in (
            "src/kicad_mcp/tools",
            "src/kicad_mcp/server.py",
            "src/kicad_mcp/tool_registry.py",
            "scripts/check_tool_contracts.py",
            "scripts/generate_tools_reference.py",
        )
    )
    if tool_surface_changed:
        checks.extend(
            [
                Check(
                    "tool-contracts",
                    [sys.executable, "scripts/check_tool_contracts.py"],
                ),
                Check(
                    "tools-reference",
                    [sys.executable, "scripts/generate_tools_reference.py", "--check"],
                ),
            ]
        )

    metadata_triggers = {
        "pyproject.toml",
        "package.json",
        "server.json",
        "compatibility.yaml",
        "ROADMAP.md",
        "README.md",
        "docs/tools-reference.generated.md",
        "scripts/sync_mcp_metadata.py",
    }
    if any(path in metadata_triggers for path in changed):
        checks.append(
            Check(
                "metadata-sync",
                [sys.executable, "scripts/sync_mcp_metadata.py", "--check"],
            )
        )

    workflow_changed = any(
        _is_under(path, ".github/workflows")
        or path == ".github/actions-policy.json"
        or path
        in {
            "scripts/check_github_actions_policy.py",
            "scripts/check_workflows.py",
            "scripts/workflow_security.py",
        }
        for path in changed
    )
    if workflow_changed:
        checks.extend(
            [
                Check(
                    "workflow-policy",
                    [sys.executable, "scripts/check_github_actions_policy.py"],
                ),
                Check(
                    "actionlint",
                    [sys.executable, "scripts/check_workflows.py", "--actionlint"],
                ),
                Check(
                    "zizmor",
                    [sys.executable, "scripts/workflow_security.py", "--min-severity", "high"],
                ),
            ]
        )

    if web_changed:
        checks.append(
            Check(
                "web-route-tests",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/unit/test_web_routes.py",
                    "tests/unit/test_web_routes_step3.py",
                    "-q",
                ],
            )
        )

    if any(_is_under(path, "src-tauri") for path in changed):
        managed_cargo = (
            root / ".dev-tools" / "cargo" / "bin" / ("cargo.exe" if os.name == "nt" else "cargo")
        )
        cargo = str(managed_cargo) if managed_cargo.is_file() else "cargo"
        checks.append(
            Check(
                "tauri-cargo-check",
                [cargo, "check", "--manifest-path", "src-tauri/Cargo.toml"],
            )
        )

    compatibility_changed = any(
        path == "compatibility.yaml"
        or _is_under(path, "src/kicad_mcp/adapters")
        or path
        in {
            "scripts/build_adapter_matrix.py",
            "scripts/check_compatibility_matrix.py",
            "scripts/check_no_pcbnew.py",
            "scripts/runtime_policy.py",
        }
        for path in changed
    )
    if compatibility_changed:
        checks.extend(
            [
                Check("no-pcbnew", [sys.executable, "scripts/check_no_pcbnew.py"]),
                Check(
                    "adapter-matrix",
                    [sys.executable, "scripts/build_adapter_matrix.py", "--check"],
                ),
                Check(
                    "compatibility-matrix",
                    [sys.executable, "scripts/check_compatibility_matrix.py"],
                ),
                Check("runtime-policy", [sys.executable, "scripts/runtime_policy.py", "check"]),
            ]
        )

    return checks


def _executable(name: str) -> str:
    resolved = which(name)
    if resolved is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")
    return resolved


def _git_output(arguments: list[str]) -> str:
    completed = subprocess.run(
        [_executable("git"), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)
    return completed.stdout.strip()


def _validated_git_ref(ref: str) -> str:
    invalid_component = any(
        component.startswith(".") or component.endswith(".lock") for component in ref.split("/")
    )
    if (
        not _SAFE_GIT_REF.fullmatch(ref)
        or ".." in ref
        or "//" in ref
        or ref.endswith((".", "/"))
        or invalid_component
    ):
        raise ValueError(f"base must be a safe Git ref, got {ref!r}")
    return ref


def _resolve_commit(ref: str) -> str:
    safe_ref = _validated_git_ref(ref)
    commit = _git_output(["rev-parse", "--verify", "--end-of-options", f"{safe_ref}^{{commit}}"])
    if not _GIT_OBJECT_ID.fullmatch(commit):
        raise ValueError("git rev-parse returned an invalid commit object id")
    return commit


def changed_files(base: str | None) -> list[str]:
    if base:
        base_commit = _resolve_commit(base)
        from_ref = _git_output(["merge-base", base_commit, "HEAD"])
        to_ref = "HEAD"
    else:
        from_ref = os.environ.get("PRE_COMMIT_FROM_REF", "").strip()
        to_ref = os.environ.get("PRE_COMMIT_TO_REF", "HEAD").strip() or "HEAD"
        if not from_ref or from_ref == ZERO_SHA:
            fallback = os.environ.get("PRE_PUSH_BASE", "origin/main")
            from_ref = _git_output(["merge-base", fallback, to_ref])

    output = _git_output(["diff", "--name-only", "--diff-filter=ACMRTUXB", f"{from_ref}..{to_ref}"])
    return [line for line in output.splitlines() if line]


def _run(check: Check) -> int:
    print(f"pre-push: {check.name}")
    completed = subprocess.run(check.command, cwd=ROOT, check=False)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", help="Compare HEAD against this ref instead of hook refs")
    parser.add_argument("--dry-run", action="store_true", help="Print the selected commands")
    args = parser.parse_args(argv)

    changed = changed_files(args.base)
    if not changed:
        print("pre-push: no changed files to check.")
        return 0

    plan = build_plan(changed)
    if not plan:
        print("pre-push: no local checks selected; CI remains authoritative.")
        return 0

    print("pre-push: changed files:")
    for path in changed:
        print(f"  - {path}")

    if args.dry_run:
        for check in plan:
            print(f"[{check.name}] {' '.join(check.command)}")
        return 0

    for check in plan:
        exit_code = _run(check)
        if exit_code != 0:
            return exit_code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
