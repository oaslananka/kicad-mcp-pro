"""Fail-closed coverage for the opt-in Codex native readonly reproducer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.probe_codex_native_readonly import _repo_skills

ROOT = Path(__file__).resolve().parents[2]
PROBE = ROOT / "scripts/probe_codex_native_readonly.py"
SOURCE = "57c0efb1f072f5fffbf1f527ee2348448705e32d"
SKILLS = {
    "drc-check",
    "fabrication-output",
    "kicad-design-review",
    "pcb-design",
    "schematic-review",
    "visual-excellence",
    "wired-subcircuit-design",
}


def _input_rows(root: Path) -> list[dict[str, str]]:
    return [
        {
            "name": f"kicad-pro:{name}",
            "path": str(root / ".agents" / "skills" / name / "SKILL.md"),
        }
        for name in sorted(SKILLS)
    ]


def test_project_skills_must_be_real_checkout_paths() -> None:
    got = _repo_skills({"data": [{"skills": _input_rows(ROOT)}]}, ROOT)
    assert set(got) == SKILLS
    for name, path in got.items():
        assert path == f".agents/skills/{name}/SKILL.md"


def test_malformed_skill_payload_rejected() -> None:
    for payload in ({"data": "invalid"}, {"data": [{"skills": "invalid"}]}, {"data": [1]}):
        with pytest.raises(ValueError, match="invalid"):
            _repo_skills(payload, ROOT)


def test_missing_skill_cannot_pass() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        _repo_skills({"data": [{"skills": _input_rows(ROOT)[:-1]}]}, ROOT)


def test_duplicate_skill_cannot_pass() -> None:
    rows = _input_rows(ROOT)
    with pytest.raises(ValueError, match="duplicate"):
        _repo_skills({"data": [{"skills": rows + [rows[0]]}]}, ROOT)


def test_outside_checkout_skill_cannot_pass(tmp_path: Path) -> None:
    rows = _input_rows(ROOT)
    external = tmp_path / "SKILL.md"
    external.write_text("test", encoding="utf-8")
    rows[0]["path"] = str(external)
    with pytest.raises(ValueError, match="outside"):
        _repo_skills({"data": [{"skills": rows}]}, ROOT)


def test_invalid_source_sha_rejected_before_host_start(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PROBE),
            "--python",
            sys.executable,
            "--expected-source-sha",
            "a" * 40,
            "--output-dir",
            str(tmp_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "status": "rejected",
        "reason": "probe_incomplete_or_unsafe",
    }
    assert not list(tmp_path.iterdir())
