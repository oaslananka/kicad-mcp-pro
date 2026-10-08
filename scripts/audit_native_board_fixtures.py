#!/usr/bin/env python3
"""Reproducible KiCad CLI fixture readiness audit; NOT autonomous board success.

All KiCad commands execute on isolated temporary *copies* of the reviewed
repository fixtures. Never let KiCad create project-local .kicad_prl files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import stat
import statistics

# Reviewed bounded native process execution with root-owned OS binaries.
import subprocess  # nosec B404
import tempfile
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
FIXTURES = {
    "mcu": "tests/fixtures/benchmark_projects/pass_minimal_mcu_board",
    "sensor": "tests/fixtures/benchmark_projects/pass_sensor_node",
    "large": "packages/kicad-fixtures/fixtures/large-board",
    "esp32-gallery": "examples/gallery/esp32-c3-wroom-02-breakout",
}
CORPUS = ("esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc")
SUPPORTED = {".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru"}
VIOLATIONS = re.compile(r"Found (\d+) violations")
FOOTPRINTS = re.compile(r"(?m)^\s*\(footprint\s")
SCHEMA = "native-fixture-readiness.v0"


def _trusted_system_executable(value: str, expected_name: str) -> str:
    """Only execute a pinned-name, non-writable OS-supplied native tool."""
    candidate = Path(value)
    trusted_dirs = (Path("/usr/bin"), Path("/usr/local/bin"))
    if (
        platform.system() != "Linux"
        or not candidate.is_absolute()
        or candidate.name != expected_name
        or candidate.parent not in trusted_dirs
    ):
        raise ValueError("native CLI executable must be from a trusted system directory")
    try:
        resolved = candidate.resolve(strict=True)
        metadata = resolved.stat()
        mode = metadata.st_mode
    except OSError as exc:
        raise ValueError("trusted native CLI executable is unavailable") from exc
    if (
        resolved.parent not in trusted_dirs
        or resolved.name != expected_name
        or not resolved.is_file()
        or not (mode & stat.S_IXUSR)
        or metadata.st_uid != 0
        or (mode & (stat.S_IWGRP | stat.S_IWOTH))
    ):
        raise ValueError("unsafe native CLI executable or permissions")
    return str(resolved)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(root: Path) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("fixture root must be a real directory")
    files = sorted(
        (p for p in root.rglob("*") if p.suffix in SUPPORTED),
        key=lambda p: p.relative_to(root).as_posix(),
    )
    if not files or any(p.is_symlink() or not p.is_file() for p in files):
        raise ValueError("missing, symlinked or invalid KiCad source")
    if not any(p.suffix == ".kicad_pcb" for p in files):
        raise ValueError("fixture must contain a KiCad PCB")
    return files


def _percentile95(samples: list[float]) -> float:
    ordered = sorted(samples)
    # Nearest-rank p95 avoids extrapolating beyond the observed maximum.
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _run_native(
    binary: str, command: list[str], *, cwd: Path, timeout: float
) -> tuple[int | None, str, float]:
    started = time.perf_counter()
    try:
        trusted_cli = _trusted_system_executable(binary, "kicad-cli")
        if trusted_cli != "/usr/bin/kicad-cli":
            raise ValueError("native benchmark requires the pinned system KiCad CLI")
        process = subprocess.run(  # nosec B603
            ["/usr/bin/kicad-cli", *command],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, "timeout", (time.perf_counter() - started) * 1000
    except OSError:
        return None, "execution_failure", (time.perf_counter() - started) * 1000
    message = process.stdout + "\n" + process.stderr
    if process.returncode == 0:
        status = "clean"
    elif (match := VIOLATIONS.search(message)) and int(match.group(1)) > 0:
        status = "violations"
    else:
        status = "native_error"
    return process.returncode, status, (time.perf_counter() - started) * 1000


def _native_case(case: str, cli: str, *, samples: int, timeout: float) -> dict[str, Any]:
    original = REPO / FIXTURES[case]
    sources = _source_files(original)
    boards = [file for file in sources if file.suffix == ".kicad_pcb"]
    if len(boards) != 1:
        raise ValueError("native fixture must have exactly one PCB")
    board = boards[0]
    files = {file.relative_to(original).as_posix(): _sha(file) for file in sources}
    # Counts source syntax only; this is NOT a native parsed netlist count.
    footprints = len(FOOTPRINTS.findall(board.read_text(encoding="utf-8")))
    with tempfile.TemporaryDirectory(prefix="kicad-native-fixture-") as temp:
        dest = Path(temp)
        for file in sources:
            copy = dest / file.relative_to(original)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, copy)
            if _sha(copy) != files[file.relative_to(original).as_posix()]:
                raise ValueError("native fixture changed during scratch copy")
        board_name = board.relative_to(original).as_posix()
        commands = ["pcb", "drc", "--exit-code-violations", "-o", "drc-audit.txt", board_name]
        observations: list[dict[str, Any]] = []
        for _ in range(samples):
            rc, status, duration = _run_native(cli, commands, cwd=dest, timeout=timeout)
            report = dest / "drc-audit.txt"
            raw_report = report.read_text(encoding="utf-8") if report.exists() else ""
            # Reports may contain KiCad timestamps; keep counts, NOT raw text.
            match = re.search(r"Found (\d+) DRC violations", raw_report)
            if match is None:
                match = VIOLATIONS.search(raw_report)
            observations.append(
                {
                    "status": status,
                    "exit_code": rc,
                    "violation_count": int(match.group(1)) if match else None,
                    "duration_ms": round(duration, 3),
                }
            )
            report.unlink(missing_ok=True)
    durations = [obs["duration_ms"] for obs in observations]
    return {
        "fixture_id": case,
        "root": FIXTURES[case],
        "pcb_footprint_source_count": footprints,
        "qualifies_944_min_1000_components": footprints >= 1000,
        "sources_sha256": files,
        "drc_observations": observations,
        "drc_p50_ms": round(statistics.median(durations), 3),
        "drc_p95_ms": round(_percentile95(durations), 3),
        "native_peak_rss_kib": None,
        "native_peak_rss_note": "not measured; no peak RSS claim",
        "is_autonomous_reference_success": False,
    }


def _reference_readiness() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    base = REPO / "docs/evidence/reference-boards"
    for board_id in CORPUS:
        root = base / board_id / "v1"
        files = {
            name: root / name
            for name in (
                "specification.md",
                "original-prompt.md",
                "benchmark.json",
                "attempt-manifest.json",
            )
        }
        manifests = files["attempt-manifest.json"]
        attempt_entries: int | None = None
        if manifests.is_file() and not manifests.is_symlink():
            try:
                parsed = json.loads(manifests.read_text(encoding="utf-8"))
                if isinstance(parsed["attempts"], list):
                    attempt_entries = len(parsed["attempts"])
            except (KeyError, OSError, TypeError, ValueError):
                pass
        results.append(
            {
                "board_id": board_id,
                "reference_path": root.relative_to(REPO).as_posix(),
                "input_files_sha256": {
                    name: _sha(path)
                    for name, path in files.items()
                    if path.is_file() and not path.is_symlink()
                },
                "attempt_manifest_entry_count_unverified": attempt_entries,
                "autonomous_success_verified_by_this_audit": False,
                "status": "requires_independent_attempt_and_native_evidence",
                "warning": (
                    "Input specifications and attempt metadata alone are NOT "
                    "a completed autonomous KiCad board or manufacturing result."
                ),
            }
        )
    return results


def run_audit(
    cli: str, *, cases: tuple[str, ...], samples: int, timeout: float, sha: str
) -> dict[str, Any]:
    if samples < 1 or samples > 20 or timeout < 1 or timeout > 180:
        raise ValueError("invalid bounded audit settings")
    if not cases or len(set(cases)) != len(cases) or any(k not in FIXTURES for k in cases):
        raise ValueError("fixture must be explicitly allowlisted")
    trusted_cli = _trusted_system_executable(cli, "kicad-cli")
    if trusted_cli != "/usr/bin/kicad-cli":
        raise ValueError("native benchmark requires the pinned system KiCad CLI")
    version = subprocess.run(  # nosec B603
        ["/usr/bin/kicad-cli", "version"], capture_output=True, text=True, check=True, timeout=15
    ).stdout.strip()
    if not version or len(version) > 100:
        raise ValueError("KiCad CLI version is unavailable")
    return {
        "schema_version": SCHEMA,
        "source_sha": sha,
        "kicad_cli_version": version,
        "execution_platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
        },
        "classification": "existing_fixture_readiness_not_agent_outcome",
        "sample_count_per_case": samples,
        "peak_rss_measured": False,
        "cases": [
            _native_case(case, trusted_cli, samples=samples, timeout=timeout) for case in cases
        ],
        "reference_corpus": _reference_readiness(),
        "limitations": [
            "Existing repo fixtures are not clean-start autonomous reference boards.",
            "DRC execution or a valid parse is not equivalent to a passing DRC.",
            "Footprint source count is not a verified component or hierarchy count.",
            "No native peak RSS, inspect/update latency, or graph equivalence was measured.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=tuple(FIXTURES))
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    binary = shutil.which("kicad-cli")
    if binary is None:
        parser.error("kicad-cli not installed; cannot manufacture benchmark evidence")
    binary = _trusted_system_executable(binary, "kicad-cli")
    if binary != "/usr/bin/kicad-cli":
        parser.error("audit requires the pinned /usr/bin/kicad-cli")
    git = shutil.which("git")
    if git is None:
        parser.error("git not installed; source provenance unavailable")
    git = _trusted_system_executable(git, "git")
    if git != "/usr/bin/git":
        parser.error("audit requires the root-owned system git executable")
    sha = subprocess.run(  # nosec B603
        ["/usr/bin/git", "rev-parse", "HEAD"],
        cwd=REPO,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.strip()
    result = run_audit(
        binary,
        cases=tuple(args.case or FIXTURES),
        samples=args.samples,
        timeout=args.timeout,
        sha=sha,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        # Never write to a project fixture or reference evidence directory.
        path = args.output.resolve()
        if path.is_relative_to(REPO):
            parser.error("audit reports must not mutate the repository checkout")
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        except FileExistsError:
            parser.error("audit report already exists; refusing to replace evidence")
        print(f"Audit report written to {path.name} (outside checkout)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
