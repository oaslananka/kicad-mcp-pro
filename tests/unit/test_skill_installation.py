"""Consumer skill installation preserves user work and uses packaged resources."""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp import skill_installation as skills


@pytest.fixture
def payload(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    files = {
        "pcb-design/SKILL.md": b"---\nname: pcb-design\ndescription: Review PCB.\n---\n",
        "pcb-design/references/notes.md": b"Keep native checks.\n",
        "drc-check/SKILL.md": b"---\nname: drc-check\ndescription: Native DRC.\n---\n",
    }
    monkeypatch.setattr(skills, "bundled_skill_files", lambda: dict(files))
    return files


def test_packaged_skills_equal_canonical_sources() -> None:
    canonical = Path(__file__).resolve().parents[2] / "skills"
    expected = {
        path.relative_to(canonical).as_posix(): path.read_bytes()
        for path in canonical.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert skills.bundled_skill_files() == expected


@pytest.mark.parametrize(
    ("agent", "scope", "relative"),
    [
        ("claude-code", "project", ".claude/skills"),
        ("codex", "user", ".agents/skills"),
        ("gemini", "project", ".gemini/skills"),
        ("opencode", "project", ".opencode/skills"),
        ("cursor", "project", ".cursor/skills"),
        ("vscode", "project", ".github/skills"),
    ],
)
def test_installs_in_host_discovery_location_and_is_repeatable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload, agent, scope, relative
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = skills.install_agent_skills(agent, scope, tmp_path)
    assert result.root == tmp_path / relative
    assert result.count == 2
    for name, content in payload.items():
        assert (result.root / name).read_bytes() == content
    first = {p: p.stat().st_mtime_ns for p in result.root.rglob("*") if p.is_file()}
    assert skills.install_agent_skills(agent, scope, tmp_path).count == 2
    assert first == {p: p.stat().st_mtime_ns for p in result.root.rglob("*") if p.is_file()}


def test_preflight_does_not_create_files(tmp_path: Path, payload) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path, write=False)
    assert result.count == 2
    assert not (tmp_path / ".cursor").exists()


def test_conflicting_unowned_skill_fails_before_installing_anything(
    tmp_path: Path, payload
) -> None:
    existing = tmp_path / ".cursor/skills/pcb-design"
    existing.mkdir(parents=True)
    custom = existing / "SKILL.md"
    custom.write_text("My private workflow")
    with pytest.raises(ValueError, match="modified|owned|conflict"):
        skills.install_agent_skills("cursor", "project", tmp_path)
    assert custom.read_text() == "My private workflow"
    assert not (existing.parent / "drc-check").exists()


def test_owned_update_backs_up_previous_files(tmp_path: Path, payload) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path)
    old = payload["pcb-design/SKILL.md"]
    payload["pcb-design/SKILL.md"] = old + b"Updated native checks.\n"
    skills.install_agent_skills("cursor", "project", tmp_path)
    assert (result.root / "pcb-design/SKILL.md").read_bytes() == payload["pcb-design/SKILL.md"]
    backups = result.root.parent / ".kicad-mcp-pro-skill-backups"
    assert any(path.read_bytes() == old for path in backups.glob("*/pcb-design/SKILL.md"))


@pytest.mark.parametrize("extra", ["private.md", "references/.kicad-mcp-pro.json"])
def test_user_edit_or_extra_file_prevents_update_and_removal(
    tmp_path: Path, payload, extra
) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path)
    custom = result.root / "pcb-design" / extra
    custom.parent.mkdir(exist_ok=True)
    custom.write_text("Do not delete")
    payload["pcb-design/SKILL.md"] += b"Upstream update\n"
    with pytest.raises(ValueError, match="modified|owned|conflict"):
        skills.install_agent_skills("cursor", "project", tmp_path)
    with pytest.raises(ValueError, match="modified|owned|conflict"):
        skills.remove_agent_skills("cursor", "project", tmp_path)
    assert custom.read_text() == "Do not delete"
    assert (result.root / "drc-check/SKILL.md").exists()


def test_removal_leaves_unrelated_skills_and_backup_files(tmp_path: Path, payload) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path)
    unrelated = result.root / "my-review"
    unrelated.mkdir()
    (unrelated / "SKILL.md").write_text("Mine")
    assert skills.remove_agent_skills("cursor", "project", tmp_path).count == 2
    assert (unrelated / "SKILL.md").read_text() == "Mine"
    assert not (result.root / "pcb-design").exists()
    assert skills.remove_agent_skills("cursor", "project", tmp_path).count == 0


def test_identical_unowned_skill_is_reused_but_never_removed(tmp_path: Path, payload) -> None:
    root = tmp_path / ".cursor/skills"
    for name, content in payload.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    skills.install_agent_skills("cursor", "project", tmp_path)
    assert skills.remove_agent_skills("cursor", "project", tmp_path).count == 0
    assert (root / "pcb-design/SKILL.md").exists()


@pytest.mark.parametrize("linked", [".cursor", ".cursor/skills", ".cursor/skills/pcb-design"])
def test_symlinks_fail_closed(tmp_path: Path, payload, linked: str) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tmp_path / linked
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="linked|symlink"):
        skills.install_agent_skills("cursor", "project", tmp_path)
    assert list(outside.iterdir()) == []


def test_unsupported_host_is_explicit_and_does_not_write(tmp_path: Path, payload) -> None:
    result = skills.install_agent_skills("claude-desktop", "user", tmp_path)
    assert result.root is None
    assert result.count == 0
    assert "not" in result.message.lower()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("name", ["../escape/SKILL.md", "/escape/SKILL.md", "pcb-design/../escape"])
def test_resource_traversal_is_rejected(tmp_path: Path, payload, name: str) -> None:
    payload[name] = b"Untrusted resource"
    with pytest.raises(ValueError):
        skills.install_agent_skills("cursor", "project", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_failed_owned_update_restores_previous_skill(tmp_path: Path, monkeypatch, payload) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path)
    old = payload["pcb-design/SKILL.md"]
    payload["pcb-design/SKILL.md"] += b"New release\n"
    replace = skills.os.replace
    failed = False

    def fail_once(source, destination) -> None:
        nonlocal failed
        if (
            not failed
            and Path(source).parent.name.startswith(".kicad-mcp-skills-")
            and Path(source).name == "pcb-design"
        ):
            failed = True
            raise OSError("Simulated disk failure")
        replace(source, destination)

    monkeypatch.setattr(skills.os, "replace", fail_once)
    with pytest.raises(OSError, match="disk failure"):
        skills.install_agent_skills("cursor", "project", tmp_path)
    assert (result.root / "pcb-design/SKILL.md").read_bytes() == old


def test_invalid_ownership_marker_cannot_authorize_overwrite(tmp_path: Path, payload) -> None:
    result = skills.install_agent_skills("cursor", "project", tmp_path)
    (result.root / "pcb-design/.kicad-mcp-pro.json").write_text("not json")
    payload["pcb-design/SKILL.md"] += b"New upstream version\n"
    with pytest.raises(ValueError, match="conflict"):
        skills.install_agent_skills("cursor", "project", tmp_path)


def test_missing_bundled_skill_entrypoint_never_writes(tmp_path: Path, payload) -> None:
    del payload["pcb-design/SKILL.md"]
    with pytest.raises(ValueError, match="SKILL.md"):
        skills.install_agent_skills("cursor", "project", tmp_path)
    assert list(tmp_path.iterdir()) == []
