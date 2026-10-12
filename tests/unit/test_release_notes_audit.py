"""Immutable release-note coverage regression tests."""

import json
from pathlib import Path

import pytest
from git import Git

from scripts.audit_release_notes import AuditError, audit, version_notes


def test_published_43_late_merge_is_not_in_notes() -> None:
    root = Path(__file__).resolve().parents[2]
    try:
        result = audit(root, "4.3.0", "4.2.0", "mcp-server-v4.3.0", {"mcp-server"})
    except AuditError as exc:
        if "git rev-parse failed" in str(exc):
            pytest.skip("tag unavailable in shallow checkout")
        raise
    rows = result["families"]["mcp-server"]["commits"]
    assert any(
        row["sha"] == "d8ca28e0dbddd8b57d7ddccf967b4e26135db073" and row["status"] == "missing"
        for row in rows
    )
    assert any(r["status"] == "matched" for r in rows)
    assert any(r["status"] == "excluded" for r in rows)


def test_version_section_absence_or_duplication_fails_closed() -> None:
    with pytest.raises(AuditError):
        version_notes("## [1.0.0] (old)", "1.1.0")
    with pytest.raises(AuditError):
        version_notes("## [1.1.0]\n## [1.1.0]", "1.1.0")


def test_unicode_digit_version_rejected() -> None:
    with pytest.raises(AuditError, match="versions must be numeric"):
        audit(Path("."), "４.３.０", "4.2.0", "HEAD", {"mcp-server"})


def _git(repo: Path, *args: str) -> str:
    return Git(repo).execute(["git", "-C", str(repo), *args]).strip()


def _write_commit(repo: Path, path: str, value: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def test_late_user_change_omitted_from_draft_in_synthetic_history(tmp_path: Path) -> None:
    repo = tmp_path / "history"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Audit")
    _git(repo, "config", "user.email", "audit@example.invalid")
    config = {
        "packages": {
            ".": {"component": "mcp-server", "tag-prefix": "mcp-server-v"},
            "packages/mcp-npm": {"component": "mcp-npm", "tag-prefix": "mcp-npm-v"},
            "src-tauri": {"component": "kicad-mcp-gui", "tag-prefix": "kicad-mcp-gui-v"},
        }
    }
    _write_commit(repo, "release-please-config.json", json.dumps(config), "chore: init")
    for path in ["CHANGELOG.md", "packages/mcp-npm/CHANGELOG.md", "src-tauri/CHANGELOG.md"]:
        _write_commit(repo, path, "## [1.0.0] (base)\n", "docs: baseline")
    for component in ["mcp-server", "mcp-npm", "kicad-mcp-gui"]:
        _git(repo, "tag", f"{component}-v1.0.0")
    listed = _write_commit(
        repo, "packages/mcp-npm/launcher.js", "ok", "fix(wrapper): handle empty input"
    )
    late = _write_commit(repo, "src/server.py", "safety", "feat(server): reject unsafe input")
    _write_commit(repo, "docs/guide.md", "readme", "docs: edit internal guide")
    for path in ["CHANGELOG.md", "packages/mcp-npm/CHANGELOG.md", "src-tauri/CHANGELOG.md"]:
        _write_commit(
            repo,
            path,
            f"## [1.1.0] (candidate)\n* fix (https://github.com/test/repo/commit/{listed})\n"
            "## [1.0.0] (base)\n",
            "docs: candidate draft",
        )
    result = audit(repo, "1.1.0", "1.0.0", "HEAD", {"mcp-server", "mcp-npm", "kicad-mcp-gui"})
    server = result["families"]["mcp-server"]["commits"]
    assert any(r["sha"] == late and r["status"] == "missing" for r in server)
    npm = result["families"]["mcp-npm"]["commits"]
    assert any(r["sha"] == listed and r["status"] == "matched" for r in npm)
    assert any(r["sha"] == late and r["status"] == "cross_component_review" for r in npm)
    assert result["families"]["kicad-mcp-gui"]["summary"]["missing"] == 0
    with pytest.raises(AuditError):
        audit(repo, "1.2.0", "1.0.0", "HEAD", {"mcp-server"})
    with pytest.raises(AuditError):
        audit(repo, "1.1.0", "0.0.9", "HEAD", {"mcp-server"})
