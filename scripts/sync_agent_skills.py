"""Mirror canonical Agent Skills into host-discovery paths without semantic drift.

Use --write for deliberate refresh; CI uses --check and never rewrites files.
Only the seven enumerated public KiCad skills are synchronized. Other
host-specific skills remain independently owned.
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


def _preflight_mirror_paths(expected: dict[Path, bytes]) -> None:
    """Fail closed on linked ancestor paths before updating any generated skill."""
    for root in HOST_ROOTS:
        _reject_linked_path(root)
        for name in SKILLS:
            _reject_linked_path(root / name)
    for target in expected:
        _reject_linked_path(target)
    for root in HOST_ROOTS:
        for name in SKILLS:
            directory = root / name
            if directory.exists():
                for item in directory.rglob("*"):
                    _reject_linked_path(item)


def run(*, write: bool) -> int:
    expected = expected_skill_files()
    _preflight_mirror_paths(expected)
    discrepancies: list[str] = []
    for target, content in expected.items():
        if target.is_symlink():
            raise ValueError(f"Generated skill target symlink not permitted: {target}")
        if not target.is_file() or target.read_bytes() != content:
            discrepancies.append(str(target.relative_to(ROOT)))
            if write:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    for root in HOST_ROOTS:
        for name in SKILLS:
            target_dir = root / name
            if target_dir.is_symlink():
                raise ValueError(f"Generated skill directory symlink not permitted: {target_dir}")
            if not target_dir.exists():
                continue
            for existing in target_dir.rglob("*"):
                if existing.is_symlink():
                    raise ValueError(f"Generated skill path symlink not permitted: {existing}")
                if existing.is_file() and existing not in expected:
                    discrepancies.append(str(existing.relative_to(ROOT)))
                    if write:
                        existing.unlink()
    if discrepancies:
        print("Agent Skills mirror drift: " + ", ".join(discrepancies[:12]))
    if write:
        for root in HOST_ROOTS:
            for name in SKILLS:
                directory = root / name
                if directory.exists():
                    # Remove empty abandoned directories after generated files are removed.
                    for child in sorted(directory.rglob("*"), reverse=True):
                        if child.is_dir() and not any(child.iterdir()):
                            child.rmdir()
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
