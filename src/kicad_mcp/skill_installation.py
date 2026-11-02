"""Install the bundled product skills without replacing user-owned workflows.

Native plugin/extension managers remain an alternative. This module only owns
its explicitly marked directories; it never registers a marketplace or a hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath

_MARKER = ".kicad-mcp-pro.json"
_UNSUPPORTED_HOST = "Portable skill installation is not supported for this host"
_DIRECTORIES = {
    "claude-code": ".claude/skills",
    "codex": ".agents/skills",
    "gemini": ".gemini/skills",
    "opencode": ".opencode/skills",
    "cursor": ".cursor/skills",
    "vscode": ".github/skills",
}


@dataclass(frozen=True)
class SkillInstallResult:
    """Filesystem installation state, not proof of discovery by an agent."""

    root: Path | None
    count: int
    message: str


def bundled_skill_files() -> dict[str, bytes]:
    """Read generated package resources, including references and scripts."""
    root = files("kicad_mcp").joinpath("data", "agent_skills")
    result: dict[str, bytes] = {}

    def visit(folder: Traversable, prefix: str) -> None:
        for entry in folder.iterdir():
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            name = prefix + entry.name
            if entry.is_dir():
                visit(entry, name + "/")
            else:
                result[name] = entry.read_bytes()

    visit(root, "")
    return result


def _root(agent: str, scope: str, project_dir: Path) -> Path | None:
    from .setup import AGENTS

    if agent not in AGENTS or scope not in AGENTS[agent].supports_scope:
        raise ValueError("Unsupported agent or skill installation scope")
    if agent not in _DIRECTORIES:
        return None
    relative = _DIRECTORIES[agent]
    if agent == "opencode" and scope == "user":
        relative = ".config/opencode/skills"
    return (Path.home() if scope == "user" else project_dir.absolute()) / relative


def _unlinked(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            raise ValueError("A linked skill installation path is not permitted")


def _groups() -> dict[str, dict[str, bytes]]:
    groups: dict[str, dict[str, bytes]] = {}
    for name, content in bundled_skill_files().items():
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or len(path.parts) < 2
            or any(part in {".", ".."} or part.startswith(".") for part in path.parts)
            or "\\" in name
            or ":" in name
            or not isinstance(content, bytes)
        ):
            raise ValueError("Invalid bundled skill resource")
        groups.setdefault(path.parts[0], {})[PurePosixPath(*path.parts[1:]).as_posix()] = content
    if not groups or any("SKILL.md" not in group for group in groups.values()):
        raise ValueError("Bundled skill is missing SKILL.md")
    return groups


def _contents(directory: Path) -> dict[str, bytes]:
    _unlinked(directory)
    result: dict[str, bytes] = {}
    for path in directory.rglob("*"):
        _unlinked(path)
        if path.is_file() and path != directory / _MARKER:
            result[path.relative_to(directory).as_posix()] = path.read_bytes()
        elif not path.is_dir() and path != directory / _MARKER:
            raise ValueError("Unsupported skill file")
    return result


def _hashes(content: dict[str, bytes]) -> dict[str, str]:
    return {name: hashlib.sha256(value).hexdigest() for name, value in content.items()}


def _owned(directory: Path, actual: dict[str, bytes]) -> bool:
    marker = directory / _MARKER
    _unlinked(marker)
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return (
        isinstance(data, dict)
        and data.get("owner") == "kicad-mcp-pro"
        and data.get("files") == _hashes(actual)
    )


def _plan(root: Path, groups: dict[str, dict[str, bytes]]) -> list[str]:
    _unlinked(root)
    changed = []
    for name, expected in groups.items():
        target = root / name
        _unlinked(target)
        if target.exists():
            actual = _contents(target)
            if actual == expected:
                continue
            if not _owned(target, actual):
                raise ValueError(f"Skill conflict: '{name}' is not owned or was modified")
        changed.append(name)
    return changed


def _stage_skill(target: Path, content: dict[str, bytes]) -> None:
    for relative, data in content.items():
        file = target / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(data)
    (target / _MARKER).write_text(
        json.dumps({"owner": "kicad-mcp-pro", "files": _hashes(content)}), encoding="utf-8"
    )


def _replace_skill(root: Path, staging: Path, name: str, expected: dict[str, bytes]) -> None:
    destination = root / name
    if not _plan(root, {name: expected}):
        return
    backup = None
    if destination.exists():
        backup_root = root.parent / ".kicad-mcp-pro-skill-backups"
        _unlinked(backup_root)
        backup_root.mkdir(exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix=name + "-", dir=backup_root)) / name
        os.replace(destination, backup)
    try:
        os.replace(staging / name, destination)
    except OSError:
        if backup is not None:
            os.replace(backup, destination)
        raise


def install_agent_skills(
    agent: str, scope: str, project_dir: Path, *, write: bool = True
) -> SkillInstallResult:
    """Preflight every target; reuse identical skills and back up owned updates."""
    root = _root(agent, scope, project_dir)
    if root is None:
        return SkillInstallResult(None, 0, _UNSUPPORTED_HOST)
    groups = _groups()
    changed = _plan(root, groups)
    if write and changed:
        root.parent.mkdir(parents=True, exist_ok=True)
        # Stage outside discovery so temporary/backup SKILL.md files cannot
        # become duplicate live skills, even in recursively scanning hosts.
        with tempfile.TemporaryDirectory(prefix=".kicad-mcp-skills-", dir=root.parent) as temporary:
            staging = Path(temporary)
            for name in changed:
                _stage_skill(staging / name, groups[name])
            _plan(root, groups)
            root.mkdir(exist_ok=True)
            for name in changed:
                _replace_skill(root, staging, name, groups[name])
    return SkillInstallResult(root, len(groups), f"{len(groups)} bundled skills ready at {root}")


def check_agent_skills(agent: str, scope: str, project_dir: Path) -> SkillInstallResult:
    """Report exact installed resources without implying model-side discovery."""
    root = _root(agent, scope, project_dir)
    if root is None:
        return SkillInstallResult(None, 0, _UNSUPPORTED_HOST)
    _unlinked(root)
    groups = _groups()
    count = sum(
        (root / name).exists() and _contents(root / name) == expected
        for name, expected in groups.items()
    )
    return SkillInstallResult(root, count, f"{count}/{len(groups)} bundled skills match at {root}")


def remove_agent_skills(agent: str, scope: str, project_dir: Path) -> SkillInstallResult:
    """Remove only unchanged, explicitly owned skills; preserve backups and peers."""
    root = _root(agent, scope, project_dir)
    if root is None:
        return SkillInstallResult(None, 0, _UNSUPPORTED_HOST)
    _unlinked(root)
    removable = []
    for name in _groups():
        target = root / name
        _unlinked(target)
        if not target.exists() or not (target / _MARKER).exists():
            continue
        if not _owned(target, _contents(target)):
            raise ValueError(f"Skill conflict: '{name}' is not owned or was modified")
        removable.append(target)
    for target in removable:
        _unlinked(target)
        if not _owned(target, _contents(target)):
            raise ValueError(f"Skill conflict: '{target.name}' was modified before removal")
        shutil.rmtree(target)
    return SkillInstallResult(root, len(removable), f"Removed {len(removable)} owned skills")
