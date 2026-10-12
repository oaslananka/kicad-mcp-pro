"""Mirror canonical Agent Skills into host-discovery paths without semantic drift.

Use --write for deliberate refresh; CI uses --check and never rewrites files.
Only the seven enumerated public KiCad skills are synchronized. Host-specific
skills, such as OpenCode's repo-repair skill, remain independently owned.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "skills"
HOST_ROOTS = (
    ROOT / ".opencode" / "skills",
    ROOT / ".agents" / "skills",
    ROOT / "integrations" / "gemini-cli" / "kicad-mcp-pro" / "skills",
)
SKILLS = (
    "drc-check",
    "fabrication-output",
    "kicad-design-review",
    "pcb-design",
    "schematic-review",
    "visual-excellence",
    "wired-subcircuit-design",
)


def _reject_linked_path(path: Path) -> None:
    """Never read/write through linked paths within the owned repository."""
    current = path
    while current != ROOT:
        if current.is_symlink():
            raise ValueError(f"Skill path symlink not permitted: {current}")
        parent = current.parent
        if parent == current:
            raise ValueError(f"Skill path outside repository: {path}")
        current = parent


def _canonical_skill_files(name: str) -> list[Path]:
    origin = CANONICAL / name
    _reject_linked_path(origin)
    skill_file = origin / "SKILL.md"
    if not skill_file.is_file() or skill_file.is_symlink():
        raise ValueError(f"Missing or linked canonical skill: {skill_file}")
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError(f"Skill YAML frontmatter missing: {skill_file}")
    _, yaml_part, _ = content.split("---", 2)
    metadata = yaml.safe_load(yaml_part)
    if (
        not isinstance(metadata, dict)
        or metadata.get("name") != name
        or not isinstance(metadata.get("description"), str)
        or not metadata["description"].strip()
    ):
        raise ValueError(f"Invalid skill identity/description: {skill_file}")
    paths = sorted(origin.rglob("*"))
    for source in paths:
        _reject_linked_path(source)
    return [source for source in paths if source.is_file()]


def expected_skill_files() -> dict[Path, bytes]:
    generated: dict[Path, bytes] = {}
    for name in SKILLS:
        origin = CANONICAL / name
        for source in _canonical_skill_files(name):
            relative = source.relative_to(origin)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            content = source.read_bytes()
            for target_root in HOST_ROOTS:
                generated[target_root / name / relative] = content
    return generated


def _stale_mirror_files(expected: dict[Path, bytes]) -> list[Path]:
    stale: list[Path] = []
    for root in HOST_ROOTS:
        for name in SKILLS:
            target_dir = root / name
            if not target_dir.exists():
                continue
            for existing in target_dir.rglob("*"):
                _reject_linked_path(existing)
                if existing.is_file() and existing not in expected:
                    stale.append(existing)
    return stale


def _collect_mirror_changes(
    expected: dict[Path, bytes],
) -> tuple[list[Path], list[Path]]:
    """Validate the whole mirror, including linked parents, before any write."""
    for target_root in HOST_ROOTS:
        _reject_linked_path(target_root)
        for name in SKILLS:
            _reject_linked_path(target_root / name)
    changed = []
    for target, content in expected.items():
        _reject_linked_path(target)
        if not target.is_file() or target.read_bytes() != content:
            changed.append(target)
    return changed, _stale_mirror_files(expected)


def _prune_empty_children(directory: Path) -> None:
    if not directory.exists():
        return
    for child in sorted(directory.rglob("*"), reverse=True):
        if child.is_dir() and not any(child.iterdir()):
            child.rmdir()


def _remove_empty_skill_directories() -> None:
    for root in HOST_ROOTS:
        for name in SKILLS:
            _prune_empty_children(root / name)


def _checked_owned_target(target: Path) -> Path:
    """Resolve and contain mirror paths; fail closed on links before filesystem writes."""
    _reject_linked_path(target)
    resolved = target.resolve()
    relative = resolved.relative_to(ROOT.resolve())
    if not any(
        relative.is_relative_to(host_root.relative_to(ROOT) / name)
        for host_root in HOST_ROOTS
        for name in SKILLS
    ):
        raise ValueError(f"Mirror output outside maintained skills: {target}")
    return resolved


def _write_mirror_target(target: Path, content: bytes) -> None:
    safe_target = _checked_owned_target(target)
    # Enforce the concrete resolved parent as a second sink-local boundary.
    # A regex filename allowlist alone would not prevent linked ancestor traversal.
    maintained_roots = tuple(
        (host_root / name).resolve() for host_root in HOST_ROOTS for name in SKILLS
    )
    if not any(root in safe_target.parents for root in maintained_roots):
        raise ValueError(f"Mirror output outside maintained skills: {target}")
    safe_target.parent.mkdir(parents=True, exist_ok=True)
    safe_target.write_bytes(content)


def _unlink_mirror_target(target: Path) -> None:
    safe_target = _checked_owned_target(target)
    safe_target.unlink()


def run(*, write: bool) -> int:
    expected = expected_skill_files()
    changed, stale = _collect_mirror_changes(expected)
    discrepancies = [str(path.relative_to(ROOT)) for path in (*changed, *stale)]
    if discrepancies:
        print("Agent Skills mirror drift: " + ", ".join(discrepancies[:12]))
    if write:
        for target in changed:
            _write_mirror_target(target, expected[target])
        for existing in stale:
            _unlink_mirror_target(existing)
        _remove_empty_skill_directories()
        return 0
    return 1 if discrepancies else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true")
    group.add_argument("--write", action="store_true")
    args = parser.parse_args()
    return run(write=args.write)


if __name__ == "__main__":
    raise SystemExit(main())
