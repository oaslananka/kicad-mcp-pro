"""Guards for the visual-excellence skill and its reference renders (Phase C follow-up)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "visual-excellence"
OPENCODE = ROOT / ".opencode" / "skills" / "visual-excellence"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_reference_renders_exist_and_are_real_pngs() -> None:
    for name in ("professional.png", "rushed.png"):
        png = SKILL / "reference" / name
        assert png.is_file(), f"missing reference render: {name}"
        data = png.read_bytes()
        assert data.startswith(_PNG_MAGIC), f"{name} is not a valid PNG"
        assert len(data) > 512, f"{name} looks empty"


def test_skill_references_the_reference_renders() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "reference/professional.png" in text
    assert "reference/rushed.png" in text


def test_opencode_mirror_is_identical() -> None:
    # OpenCode discovers skills from .opencode/skills; the two copies must match.
    assert (SKILL / "SKILL.md").read_bytes() == (OPENCODE / "SKILL.md").read_bytes()
    for name in ("professional.png", "rushed.png"):
        assert (SKILL / "reference" / name).read_bytes() == (
            OPENCODE / "reference" / name
        ).read_bytes()
