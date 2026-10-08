"""Pinned native KiCad demo benchmarks cannot manufacture performance evidence."""

from __future__ import annotations

import hashlib
import json

# Import used solely to simulate TimeoutExpired in test doubles.
import subprocess  # nosec B404
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import benchmark_kicad_large_demo as bench


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root = tmp_path / "vendor" / "test-demo"
    root.mkdir(parents=True)
    sources = {
        "project.kicad_pcb": "(kicad_pcb (footprint))",
        "project.kicad_pro": "{}",
        "project.kicad_sch": "(kicad_sch (root))",
        "power.kicad_sch": "(kicad_sch (power))",
        "LICENSE": "Apache License\nVersion 2.0\n",
    }
    for name, contents in sources.items():
        (root / name).write_text(contents)
    manifest = {
        "schema_version": "native-kicad-demo-manifest.v1",
        "demo_id": "test-demo",
        "package": "vendor-package",
        "packaged_with_kicad_version": "10.0.6",
        "license": "Apache-2.0",
        "pcb": "project.kicad_pcb",
        "minimum_pcb_footprints": 1000,
        "minimum_schematic_files": 2,
        "files": {
            name: hashlib.sha256(value.encode()).hexdigest() for name, value in sources.items()
        },
    }
    pinned = tmp_path / "manifest.json"
    pinned.write_text(json.dumps(manifest))
    monkeypatch.setattr(bench, "MANIFEST_PATH", pinned)
    # Unit tests simulate the worker; the real runner only allows OS Python.
    monkeypatch.setattr(bench, "_trusted_system_python", lambda interpreter: interpreter.resolve())
    return root, pinned


def _response(*, footprints: int = 1100, tracks: int = 2500, peak: int = 250000):
    return SimpleNamespace(
        returncode=0,
        stdout="KiCad diagnostics before report\nKICAD_NATIVE_INSPECT_V1:"
        + json.dumps(
            {
                "footprints": footprints,
                "tracks": tracks,
                "copper_layers": 8,
                "kicad_build_version": "10.0.6",
                "load_ms": 12.0,
                "inspect_ms": 2.0,
                "peak_rss_kib": peak,
            }
        ),
        stderr="",
    )


def test_vendor_input_manifest_requires_exact_hash_inventory_and_license(
    demo: tuple[Path, Path],
) -> None:
    root, pinned = demo
    manifest = json.loads(pinned.read_text())
    assert len(bench.validate_demo_files(root, manifest)) == 5
    (root / "project.kicad_sch").write_text("altered")
    with pytest.raises(ValueError, match="pinned"):
        bench.validate_demo_files(root, manifest)


def test_new_native_source_is_not_silently_ignored(demo: tuple[Path, Path]) -> None:
    root, pinned = demo
    (root / "new-sheet.kicad_sch").write_text("(kicad_sch)")
    with pytest.raises(ValueError, match="inventory"):
        bench.validate_demo_files(root, json.loads(pinned.read_text()))


def test_missing_license_and_symlinked_sources_are_rejected(demo: tuple[Path, Path]) -> None:
    root, pinned = demo
    license_file = root / "LICENSE"
    license_file.write_text("proprietary")
    with pytest.raises(ValueError, match="license"):
        bench.validate_demo_files(root, json.loads(pinned.read_text()))
    license_file.unlink()
    license_file.symlink_to(pinned)
    with pytest.raises(ValueError, match="symlinked"):
        bench.validate_demo_files(root, json.loads(pinned.read_text()))


def test_native_large_demo_reports_true_process_peak_and_p95(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _manifest = demo
    paths: list[Path] = []

    def fake_execute(cmd: list[str], **kwargs: object):
        assert Path(cmd[0]) == Path(sys.executable).resolve()
        assert cmd[1] == "-c"
        project = Path(cmd[3])
        assert project.is_file()
        assert project.parent != root
        assert (project.parent / "power.kicad_sch").exists()
        paths.append(project.parent)
        return _response(peak=180000 + len(paths))

    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bench.subprocess, "run", fake_execute)
    result = bench.benchmark_demo(
        demo_root=root,
        interpreter=Path(sys.executable),
        repeats=3,
        timeout=15,
        repository_sha="a" * 40,
    )
    assert len(paths) == 3 and len(set(paths)) == 1
    assert not paths[0].exists()
    assert result["schematic_source_files"] == 2
    assert result["native_load_ms"]["p95_nearest_rank"] == 12
    assert result["native_inspect_ms"]["p50"] == 2
    assert result["process_peak_rss_kib"]["p95_nearest_rank"] == 180003
    assert result["status"] == "native_large_project_baseline_only"
    assert "incremental mutation/update latency" in result["not_measured"]
    assert (root / "project.kicad_pcb").read_text() == "(kicad_pcb (footprint))"


@pytest.mark.parametrize(
    "bad_repeats,bad_timeout",
    [(0, 20), (11, 20), (1, 0), (1, 250)],
)
def test_unbounded_load_runs_fail_closed(
    demo: tuple[Path, Path], bad_repeats: int, bad_timeout: float
) -> None:
    with pytest.raises(ValueError):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=bad_repeats,
            timeout=bad_timeout,
            repository_sha="a" * 40,
        )


def test_native_large_benchmark_rejects_toy_board_and_mocked_success(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bench.subprocess, "run", lambda *args, **kwargs: _response(footprints=5))
    with pytest.raises(RuntimeError, match="size/metric floor"):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=1,
            timeout=10,
            repository_sha="a" * 40,
        )


def test_native_large_benchmark_cannot_hide_timeout(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")

    def expire(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired("native", 10)

    monkeypatch.setattr(bench.subprocess, "run", expire)
    with pytest.raises(RuntimeError, match="timeout"):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=1,
            timeout=10,
            repository_sha="a" * 40,
        )


def test_native_large_benchmark_refuses_inconsistent_board_identity(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")
    count = 0

    def vary(*args: object, **kwargs: object):
        nonlocal count
        count += 1
        return _response(tracks=2500 + count)

    monkeypatch.setattr(bench.subprocess, "run", vary)
    with pytest.raises(RuntimeError, match="inconsistent"):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=2,
            timeout=10,
            repository_sha="a" * 40,
        )


def test_native_memory_benchmark_platform_limit_is_explicit(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="Linux-only"):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=1,
            timeout=10,
            repository_sha="a" * 40,
        )


def test_nearest_rank_p95_stays_within_observed_samples() -> None:
    assert bench.nearest_rank_p95([5, 1, 2, 3]) == 5
    assert bench.nearest_rank_p95(list(range(1, 101))) == 95


def test_untrusted_interpreter_path_rejected_without_execution() -> None:
    with pytest.raises(ValueError, match="trusted system Python"):
        bench._trusted_system_python(Path("/untrusted/venv/python3"))
    with pytest.raises(ValueError, match="trusted system Python"):
        bench._trusted_system_python(Path("python3"))


def test_diagnostic_stdout_without_unique_worker_record_fails_closed(
    demo: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bench.platform, "system", lambda: "Linux")
    good = _response()
    monkeypatch.setattr(
        bench.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=good.stdout + "\n" + good.stdout, stderr=""
        ),
    )
    with pytest.raises(RuntimeError, match="protocol is missing or ambiguous"):
        bench.benchmark_demo(
            demo_root=demo[0],
            interpreter=Path(sys.executable),
            repeats=1,
            timeout=10,
            repository_sha="a" * 40,
        )
