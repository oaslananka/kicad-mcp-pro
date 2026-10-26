"""Fail-closed coverage for the opt-in Codex native readonly reproducer."""

from __future__ import annotations

import json
import signal
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


def test_unknown_source_sha_rejected_before_host_start(
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
    monkeypatch.setattr(probe.shutil, "which", lambda _name: sys.executable)
    fingerprints = iter(["b" * 64, "c" * 64])
    monkeypatch.setattr(probe, "_sha256_executable", lambda _path: next(fingerprints))
    calls: list[list[str]] = []

    def fake_git(argv: list[str], **_kwargs: object) -> str:
        calls.append(argv)
        if argv == ["git", "rev-parse", "HEAD"]:
            return "d" * 40
        if argv[:3] == ["git", "merge-base", "--is-ancestor"]:
            raise RuntimeError("unknown ancestor revision")
        pytest.fail("unexpected Git command")

    monkeypatch.setattr(probe, "_run", fake_git)
    monkeypatch.setattr(
        probe, "_execute", lambda *_args, **_kwargs: pytest.fail("host must not start")
    )
    assert probe.main() == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "rejected",
        "reason": "probe_incomplete_or_unsafe",
    }
    assert calls == [
        ["git", "rev-parse", "HEAD"],
        ["git", "merge-base", "--is-ancestor", "a" * 40, "d" * 40],
    ]
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


@pytest.mark.parametrize("first_wait_times_out", [False, True])
def test_process_group_cleanup_kills_surviving_children(
    monkeypatch: pytest.MonkeyPatch, first_wait_times_out: bool
) -> None:
    signals: list[tuple[int, signal.Signals]] = []
    waits: list[int] = []

    class Process:
        pid = 9467

        def wait(self, *, timeout: int) -> int:
            waits.append(timeout)
            if first_wait_times_out and len(waits) == 1:
                raise probe.subprocess.TimeoutExpired("codex", timeout)
            return 0

    monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    probe._stop_host_process_group(Process())
    assert signals == [(9467, signal.SIGTERM), (9467, signal.SIGKILL)]
    assert waits == [5, 5]


def test_output_targets_reject_preexisting_artifacts(tmp_path: Path) -> None:
    assert probe._output_targets(tmp_path) == (
        tmp_path / "codex-native-sanitized-log.json",
        tmp_path / "codex-native-smoke.json",
    )
    existing = tmp_path / "codex-native-smoke.json"
    existing.write_bytes(b"previous observation")
    with pytest.raises(RuntimeError, match="already exists"):
        probe._output_targets(tmp_path)
    assert existing.read_bytes() == b"previous observation"


def test_evidence_partial_write_rollback_preserves_preexisting_target(tmp_path: Path) -> None:
    first, second = (
        tmp_path / "codex-native-sanitized-log.json",
        tmp_path / "codex-native-smoke.json",
    )
    second.write_bytes(b"preexisting")
    with pytest.raises(FileExistsError):
        probe._write_evidence((first, second), (b"candidate", b"report"))
    assert not first.exists()
    assert second.read_bytes() == b"preexisting"


def test_evidence_success_writes_both_files(tmp_path: Path) -> None:
    first, second = probe._output_targets(tmp_path)
    probe._write_evidence((first, second), (b"sanitized", b"metadata"))
    assert first.read_bytes() == b"sanitized"
    assert second.read_bytes() == b"metadata"


def test_preexisting_output_rejected_before_native_host_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "codex-native-smoke.json").write_bytes(b"existing")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "probe_codex_native_readonly.py",
            "--python",
            sys.executable,
            "--expected-source-sha",
            SOURCE,
            "--expected-codex-sha256",
            "b" * 64,
            "--expected-python-sha256",
            "c" * 64,
            "--output-dir",
            str(tmp_path),
        ],
    )
    monkeypatch.setattr(probe.shutil, "which", lambda _name: sys.executable)
    fingerprints = iter(["b" * 64, "c" * 64])
    monkeypatch.setattr(probe, "_sha256_executable", lambda _path: next(fingerprints))

    def fake_git(argv: list[str], **_kwargs: object) -> str:
        if argv == ["git", "rev-parse", "HEAD"]:
            return SOURCE
        if argv == ["git", "status", "--porcelain", "--", "src"]:
            return ""
        pytest.fail("unexpected Git command")

    monkeypatch.setattr(probe, "_run", fake_git)
    monkeypatch.setattr(
        probe, "_execute", lambda *_args, **_kwargs: pytest.fail("host must not start")
    )
    assert probe.main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "rejected"
    assert (tmp_path / "codex-native-smoke.json").read_bytes() == b"existing"
