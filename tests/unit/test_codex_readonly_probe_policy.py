"""Fail-closed coverage for the opt-in Codex native readonly reproducer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import probe_codex_native_readonly as probe
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
    incomplete = {"data": [{"skills": _input_rows(ROOT)[:-1]}]}
    with pytest.raises(ValueError, match="incomplete"):
        _repo_skills(incomplete, ROOT)


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


def test_invalid_source_sha_rejected_before_host_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe_codex_native_readonly.py",
            "--python",
            sys.executable,
            "--expected-source-sha",
            "a" * 40,
            "--expected-codex-sha256",
            "b" * 64,
            "--expected-python-sha256",
            "c" * 64,
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(
        probe,
        "_execute",
        lambda *_args: pytest.fail("host must not start after SHA mismatch"),
    )
    code = probe.main()
    assert code == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "rejected",
        "reason": "probe_incomplete_or_unsafe",
    }
    assert not list(tmp_path.iterdir())


def test_mismatched_executable_sha_rejected_before_host_or_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe_codex_native_readonly.py",
            "--python",
            sys.executable,
            "--expected-codex-sha256",
            "a" * 64,
            "--expected-python-sha256",
            "b" * 64,
            "--expected-source-sha",
            SOURCE,
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(probe.shutil, "which", lambda _name: sys.executable)
    monkeypatch.setattr(probe, "_sha256_executable", lambda _path: "c" * 64)
    monkeypatch.setattr(
        probe,
        "_run",
        lambda *_args, **_kwargs: pytest.fail("git/host must not run"),
    )
    monkeypatch.setattr(
        probe,
        "_execute",
        lambda *_args, **_kwargs: pytest.fail("host must not start"),
    )
    assert probe.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            b'{"jsonrpc":"2.0","method":"notification"}\n{"id":3,"result":{"status":"ok"}}\n',
            {"status": "ok"},
        ),
        (b'invalid-json\n{"id":3,"result":{"status":"ok"}}\n', {"status": "ok"}),
        (b'42\n{"id":3,"result":{"status":"ok"}}\n', {"status": "ok"}),
    ],
)
def test_native_rpc_skips_malformed_or_unrelated_frames(
    raw: bytes, expected: dict[str, str]
) -> None:
    """Ignore notifications and irrelevant JSON until the matching response."""
    rpc = object.__new__(probe._AppServer)
    rpc.pending = raw
    assert rpc._matching_response(3, "example") == expected
    assert rpc.pending == b""


@pytest.mark.parametrize(
    "raw",
    [
        b'{"id":3,"error":{"message":"unavailable"}}\n',
        b'{"id":3,"result":"malformed"}\n',
    ],
)
def test_native_rpc_rejects_error_and_invalid_matching_results(raw: bytes) -> None:
    rpc = object.__new__(probe._AppServer)
    rpc.pending = raw
    with pytest.raises(RuntimeError, match="host RPC failed|unexpected host RPC"):
        rpc._matching_response(3, "example")
