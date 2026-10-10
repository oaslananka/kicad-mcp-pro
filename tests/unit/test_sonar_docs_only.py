"""Only actual documentation-only Git changes may bypass Sonar full-suite cost."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_sonar_docs_only import is_docs_only_diff

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ([], False),
        (["docs/readme.md"], True),
        (["docs/evidence/measurements.json", "docs/README.md"], True),
        (["docs/file name.md"], True),
        (["docs/ünicode.md"], True),
        (["docs/"], False),
        (["README.md"], False),
        (["sonar-project.properties"], False),
        ([".github/workflows/sonarcloud.yml"], False),
        (["src/kicad_mcp/providers/dispatch.py"], False),
        (["tests/unit/test_sonar_docs_only.py"], False),
        (["docs/evidence/file.json", "src/kicad_mcp/server.py"], False),
        (["docs/evidence/file.json", "uv.lock"], False),
        (["docs/evidence/file.json", "scripts/check_sonar_docs_only.py"], False),
    ],
)
def test_docs_only_classification(paths: list[str], expected: bool) -> None:
    raw = b"".join(item.encode("utf-8") + b"\0" for item in paths)
    assert is_docs_only_diff(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [
        b"docs/readme.md",
        b"docs/readme.md\n",
        b"docs/readme.md\0src/new.py",
        b"\0",
        b"docs/readme.md\0\0",
    ],
)
def test_docs_only_rejects_incomplete_or_malformed_git_output(raw: bytes) -> None:
    assert is_docs_only_diff(raw) is False


def test_docs_only_cli_accepts_only_bounded_docs_paths(tmp_path: Path) -> None:
    path = tmp_path / "changed-paths.bin"
    for data, code in [(b"docs/guide.md\0", 0), (b"docs/guide.md\0src/main.py\0", 1), (b"", 1)]:
        path.write_bytes(data)
        done = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/check_sonar_docs_only.py"),
                "--paths-file",
                str(path),
            ],
            check=False,
            capture_output=True,
        )
        assert done.returncode == code


def test_renaming_source_into_docs_still_requires_analysis(tmp_path: Path) -> None:
    """The workflow must use --no-renames to expose deleted analyzed source."""
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git CLI unavailable")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run([git, "init", "-q"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run([git, "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            git,
            "-c",
            "user.name=CI Fixture",
            "-c",
            "user.email=ci@example.invalid",
            "commit",
            "-qm",
            "seed",
        ],
        cwd=repo,
        check=True,
    )
    (repo / "docs").mkdir()
    (repo / "src" / "module.py").rename(repo / "docs" / "module.py")
    subprocess.run([git, "add", "-A"], cwd=repo, check=True)
    diff = subprocess.run(
        [git, "diff", "--no-renames", "--cached", "--name-only", "-z", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    assert set(diff.rstrip(b"\0").split(b"\0")) == {b"src/module.py", b"docs/module.py"}
    assert is_docs_only_diff(diff) is False
