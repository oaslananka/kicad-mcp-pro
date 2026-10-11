"""Mirror canonical Agent Skills into host-discovery paths without semantic drift.

Use `--write` for deliberate refresh; CI uses `--check` and never rewrites files.
Only the seven enumerated public KiCad skills are synchronized. Host-specific
skills, such as OpenCode's repo-repair skill, remain independently owned.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "skills"
HOST_ROOTS = (ROOT / ".opencode" / "skills", ROOT / ".agents" / "skills")
SKILLS = (
    "drc-check",
    "fabrication-output",
    "kicad-design-review",
    "pcb-design",
    "schematic-review",
    "visual-excellence",
    "wired-subcircuit-design",
)


def expected_skill_files() -> dict[Path, bytes]:
    generated: dict[Path, bytes] = {}
    for name in SKILLS:
        origin = CANONICAL / name
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
        files = sorted(p for p in origin.rglob("*") if p.is_file())
        for source in files:
            if source.is_symlink():
                raise ValueError(f"Skill source symlink not permitted: {source}")
            relative = source.relative_to(origin)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            for target_root in HOST_ROOTS:
                generated[target_root / name / relative] = source.read_bytes()
    return generated


def run(*, write: bool) -> int:
    expected = expected_skill_files()
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
