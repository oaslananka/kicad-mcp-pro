"""Never confuse native fixture readiness with agent task success."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import audit_native_board_fixtures as audit


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "fixtures" / "sample"
    root.mkdir(parents=True)
    (root / "sample.kicad_pcb").write_text(
        '(kicad_pcb\n  (footprint "Device:R")\n  (footprint "Device:C")\n)\n'
    )
    (root / "sample.kicad_sch").write_text("(kicad_sch)")
    (root / "sample.kicad_pro").write_text("{}")
    # Personal KiCad state files must never be copied into audit scratch.
    (root / "sample.kicad_prl").write_text("do-not-copy")
    monkeypatch.setattr(audit, "REPO", tmp_path)
    monkeypatch.setattr(audit, "FIXTURES", {"sample": "fixtures/sample"})
    return root


def test_p95_nearest_rank_never_extrapolates() -> None:
    assert audit._percentile95([10, 20, 30]) == 30
    assert audit._percentile95(list(range(1, 101))) == 95
    assert audit._percentile95([5]) == 5


def test_native_audit_runs_on_copy_and_preserves_canonical_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    expected_hash = hashlib.sha256((root / "sample.kicad_pcb").read_bytes()).hexdigest()
    observed: list[Path] = []

    def fake_run(
        binary: str, command: list[str], *, cwd: Path, timeout: float
    ) -> tuple[int, str, float]:
        assert binary == "kicad-cli"
        assert timeout == 12
        assert command[:3] == ["pcb", "drc", "--exit-code-violations"]
        assert (cwd / "sample.kicad_pcb").is_file()
        assert not (cwd / "sample.kicad_prl").exists()
        assert cwd != root
        observed.append(cwd)
        (cwd / "drc-audit.txt").write_text("** Found 3 DRC violations **\n")
        return 5, "violations", 10.0 + len(observed)

    monkeypatch.setattr(audit, "_run_native", fake_run)
    result = audit._native_case("sample", "kicad-cli", samples=2, timeout=12)
    assert result["pcb_footprint_source_count"] == 2
    assert not result["qualifies_944_min_1000_components"]
    assert result["sources_sha256"]["sample.kicad_pcb"] == expected_hash
    assert [x["violation_count"] for x in result["drc_observations"]] == [3, 3]
    assert result["drc_p50_ms"] == 11.5
    assert result["drc_p95_ms"] == 12.0
    assert not result["is_autonomous_reference_success"]
    assert result["native_peak_rss_kib"] is None
    assert len(observed) == 2 and observed[0] == observed[1]
    assert not observed[0].exists(), "audit scratch must be removed"
    assert hashlib.sha256((root / "sample.kicad_pcb").read_bytes()).hexdigest() == expected_hash
    assert (root / "sample.kicad_prl").read_text() == "do-not-copy"


def test_missing_or_symlinked_source_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _fixture(tmp_path, monkeypatch)
    board = root / "sample.kicad_pcb"
    board.unlink()
    with pytest.raises(ValueError, match="PCB"):
        audit._source_files(root)
    board.symlink_to(root / "sample.kicad_sch")
    with pytest.raises(ValueError, match="symlinked"):
        audit._source_files(root)


@pytest.mark.parametrize(
    "args",
    [
        {"cases": ("unknown",), "samples": 2, "timeout": 10},
        {"cases": ("sample", "sample"), "samples": 2, "timeout": 10},
        {"cases": ("sample",), "samples": 0, "timeout": 10},
        {"cases": ("sample",), "samples": 21, "timeout": 10},
        {"cases": ("sample",), "samples": 1, "timeout": 0},
        {"cases": ("sample",), "samples": 1, "timeout": 200},
    ],
)
def test_unbounded_or_unreviewed_benchmarks_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: dict
) -> None:
    _fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        audit.run_audit("kicad-cli", **args, sha="a" * 40)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (subprocess.TimeoutExpired("cli", 3), "timeout"),
        (FileNotFoundError("cli unavailable"), "execution_failure"),
    ],
)
def test_native_process_failure_is_observable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, exc: Exception, expected: str
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise exc

    monkeypatch.setattr(audit.subprocess, "run", fail)
    monkeypatch.setattr(
        audit, "_trusted_system_executable", lambda candidate, expected: "/usr/bin/kicad-cli"
    )
    code, status, duration = audit._run_native("kicad-cli", ["pcb", "drc"], cwd=tmp_path, timeout=3)
    assert code is None
    assert status == expected
    assert duration >= 0


@pytest.mark.parametrize(
    ("rc", "stdout", "expected"),
    [
        (0, "Found 0 violations", "clean"),
        (5, "Found 3 violations", "violations"),
        (3, "Failed to load board", "native_error"),
    ],
)
def test_native_exit_classification_does_not_turn_violations_into_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rc: int, stdout: str, expected: str
) -> None:
    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=rc, stdout=stdout, stderr="")

    monkeypatch.setattr(audit.subprocess, "run", fake_run)
    monkeypatch.setattr(
        audit, "_trusted_system_executable", lambda candidate, expected: "/usr/bin/kicad-cli"
    )
    return_code, status, _duration = audit._run_native(
        "kicad-cli", ["pcb", "drc"], cwd=tmp_path, timeout=10
    )
    assert return_code == rc
    assert status == expected


def test_reference_specifications_cannot_be_counted_as_completed_designs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "REPO", tmp_path)
    root = tmp_path / "docs" / "evidence" / "reference-boards" / "stm32f072-usbc" / "v1"
    root.mkdir(parents=True)
    (root / "specification.md").write_text("# spec\n")
    (root / "attempt-manifest.json").write_text('{"attempts":[{}, {}, {}]}')
    results = audit._reference_readiness()
    assert len(results) == 3
    stm = next(r for r in results if r["board_id"] == "stm32f072-usbc")
    assert stm["attempt_manifest_entry_count_unverified"] == 3
    assert stm["status"] == "requires_independent_attempt_and_native_evidence"
    assert stm["autonomous_success_verified_by_this_audit"] is False
    assert "agent" not in str(stm["input_files_sha256"])


@pytest.mark.parametrize(
    "path,reason",
    [
        ("kicad-cli", "trusted system"),
        ("/" + "tmp/kicad-cli", "trusted system"),
        ("/home/runner/kicad-cli", "trusted system"),
        ("/usr/bin/git", "trusted system"),
    ],
)
def test_untrusted_native_cli_executable_is_rejected(
    path: str, reason: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit.platform, "system", lambda: "Linux")
    with pytest.raises(ValueError, match=reason):
        audit._trusted_system_executable(path, "kicad-cli")


def test_actual_os_cli_is_trusted_when_present() -> None:
    executable = Path("/usr/bin/kicad-cli")
    if not executable.exists():
        pytest.skip("system KiCad CLI is not installed on this runner")
    assert audit._trusted_system_executable(str(executable), "kicad-cli") == str(
        executable.resolve()
    )
