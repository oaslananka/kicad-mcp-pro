from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path


def _write_fake_gh(bin_dir: Path) -> None:
    fake = bin_dir / "fake_gh.py"
    fake.write_text(
        """from __future__ import annotations

import sys

args = sys.argv[1:]
joined = " ".join(args)
if args[:3] == ["api", "-X", "GET"] and "/branches" in joined:
    print('[{"name":"main"},{"name":"develop"}]')
    raise SystemExit(0)
if args[:2] == ["pr", "list"]:
    raise SystemExit(0)
print(f"unexpected gh invocation: {joined}", file=sys.stderr)
raise SystemExit(2)
""",
        encoding="utf-8",
    )
    gh = bin_dir / "gh"
    gh.write_text(
        f'#!/usr/bin/env sh\nexec {sys.executable!r} {str(fake)!r} "$@"\n', encoding="utf-8"
    )
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    gh_cmd = bin_dir / "gh.cmd"
    gh_cmd.write_text(f'@echo off\r\n"{sys.executable}" "{fake}" %*\r\n', encoding="utf-8")


def test_branch_hygiene_no_matches_exits_zero(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_gh(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/branch_hygiene_report.py",
            "--repo",
            "oaslananka/kicad-mcp-pro",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "no stale branches found" in result.stdout


def test_branch_hygiene_strict_no_matches_exits_one(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_gh(bin_dir)

    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/branch_hygiene_report.py",
            "--repo",
            "oaslananka/kicad-mcp-pro",
            "--strict",
        ],
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 1
    assert "no stale branches found" in result.stdout
