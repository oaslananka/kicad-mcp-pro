"""Only actual documentation-only Git changes may bypass Sonar full-suite cost."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from git import Actor, Repo

from scripts.check_sonar_docs_only import is_docs_only_diff, main


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


def test_docs_only_cli_accepts_only_bounded_docs_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "changed-paths.bin"
    for data, code in [(b"docs/guide.md\0", 0), (b"docs/guide.md\0src/main.py\0", 1), (b"", 1)]:
        path.write_bytes(data)
        monkeypatch.setattr(sys, "argv", ["check_sonar_docs_only.py", "--paths-file", str(path)])
        assert main() == code


def test_renaming_source_into_docs_still_requires_analysis(tmp_path: Path) -> None:
    """The workflow's --no-renames reveals both the source removal and docs addition."""
    repo = Repo.init(tmp_path / "repo")
    source = Path(repo.working_tree_dir or "") / "src" / "module.py"
    source.parent.mkdir()
    source.write_text("x = 1\n", encoding="utf-8")
    repo.index.add(["src/module.py"])
    actor = Actor("CI Fixture", "ci@example.invalid")
    repo.index.commit("seed", author=actor, committer=actor)

    docs = source.parent.parent / "docs"
    docs.mkdir()
    source.rename(docs / "module.py")
    repo.git.add("-A")
    diff = repo.git.diff("--no-renames", "--cached", "--name-only", "-z", "HEAD")
    paths = diff.encode("utf-8")
    assert set(paths.rstrip(b"\0").split(b"\0")) == {b"src/module.py", b"docs/module.py"}
    assert is_docs_only_diff(paths) is False
