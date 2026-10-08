#!/usr/bin/env python3
"""Opt-in native PCB-load benchmark for a pinned 1,000+ footprint KiCad demo.

This measures native inspect and true process peak memory on Linux, but NOT
incremental update performance, successful PCB design, or manufacturing signoff.
No vendor KiCad design files are checked into this repository.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import stat
import statistics

# Reviewed bounded native process execution with root-owned OS binaries.
import subprocess  # nosec B404
import tempfile
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/native_demo_manifests/jetson-agx-thor-baseboard-kicad10.json"
DEFAULT_DEMO_ROOT = Path("/usr/share/kicad/demos/jetson-agx-thor-baseboard")
ALLOWED_SUFFIXES = {".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_dru"}
SCHEMA = "native-kicad-large-inspect.v0"

# Isolated worker must run under the native KiCad Python interpreter, not the
# project's uv Python virtualenv (which may not expose Debian pcbnew bindings).
WORKER = """
import json, pathlib, resource, time
import pcbnew

path = pathlib.Path(__import__('sys').argv[1])
start = time.perf_counter()
board = pcbnew.LoadBoard(str(path))
load_ms = (time.perf_counter() - start) * 1000.0
if board is None:
    raise RuntimeError('native board load returned no board')
start = time.perf_counter()
footprints = len(board.GetFootprints())
tracks = len(board.GetTracks())
copper_layers = board.GetCopperLayerCount()
inspect_ms = (time.perf_counter() - start) * 1000.0
print('KICAD_NATIVE_INSPECT_V1:' + json.dumps({
    'footprints': footprints,
    'tracks': tracks,
    'copper_layers': copper_layers,
    'load_ms': round(load_ms, 3),
    'inspect_ms': round(inspect_ms, 3),
    'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    'kicad_build_version': pcbnew.GetBuildVersion(),
}), flush=True)
"""


def _trusted_system_python(interpreter: Path) -> Path:
    """Reject executable injection from a virtualenv, writable tree or PATH."""
    system_dirs = (Path("/usr/bin"), Path("/usr/local/bin"))
    if not interpreter.is_absolute() or interpreter.parent not in system_dirs:
        raise ValueError("native KiCad interpreter must be a trusted system Python")
    try:
        resolved = interpreter.resolve(strict=True)
        metadata = resolved.stat()
        mode = metadata.st_mode
    except OSError as exc:
        raise ValueError("native KiCad Python interpreter missing") from exc
    if (
        resolved.parent not in system_dirs
        or not resolved.name.startswith("python3.")
        or not resolved.is_file()
        or not (mode & stat.S_IXUSR)
        or metadata.st_uid != 0
        or (mode & (stat.S_IWGRP | stat.S_IWOTH))
    ):
        raise ValueError("native KiCad Python interpreter is not trusted")
    return resolved


def sha256_file(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def validate_demo_files(root: Path, manifest: dict[str, Any]) -> list[Path]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("native demo root is missing or symlinked")
    if manifest.get("schema_version") != "native-kicad-demo-manifest.v1":
        raise ValueError("unsupported native input manifest")
    if manifest.get("license") != "Apache-2.0":
        raise ValueError("native demo license is not verified")
    if any(path.is_symlink() for path in root.iterdir()):
        raise ValueError("symlinked native demo file")
    expected = manifest.get("files")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("unversioned native demo files")
    sources = sorted(
        [
            file
            for file in root.iterdir()
            if file.is_file() and (file.suffix in ALLOWED_SUFFIXES or file.name == "LICENSE")
        ]
    )
    if {file.name for file in sources} != set(expected):
        raise ValueError("demo source inventory does not match the pinned manifest")
    if any(file.is_symlink() for file in sources):
        raise ValueError("symlinked native demo file")
    if sum(file.suffix == ".kicad_sch" for file in sources) < int(
        manifest.get("minimum_schematic_files", 2)
    ):
        raise ValueError("native demo is not multi-sheet")
    board_name = manifest.get("pcb")
    if (
        not isinstance(board_name, str)
        or "/" in board_name
        or "\\" in board_name
        or board_name not in expected
        or not board_name.endswith(".kicad_pcb")
    ):
        raise ValueError("invalid pinned PCB identity")
    license_text = (root / "LICENSE").read_text(encoding="utf-8")
    if "Apache License" not in license_text or "Version 2.0" not in license_text:
        raise ValueError("native demo license evidence mismatch")
    for source in sources:
        expected_digest = expected[source.name]
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or sha256_file(source) != expected_digest
        ):
            raise ValueError("native demo differs from pinned KiCad distribution source")
    return sources


def nearest_rank_p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[(95 * len(ordered) + 99) // 100 - 1]


def benchmark_demo(
    *,
    demo_root: Path,
    interpreter: Path,
    repeats: int,
    timeout: float,
    repository_sha: str,
) -> dict[str, Any]:
    if not 1 <= repeats <= 10 or not 5 <= timeout <= 180:
        raise ValueError("unbounded benchmark settings")
    if platform.system() != "Linux":
        raise RuntimeError("true native peak RSS benchmark is currently Linux-only")
    runtime = _trusted_system_python(interpreter)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    sources = validate_demo_files(demo_root, manifest)
    board_name = manifest["pcb"]
    measurements: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="kicad-native-large-") as location:
        scratch = Path(location)
        for source in sources:
            copied = scratch / source.name
            shutil.copyfile(source, copied)
            if sha256_file(copied) != manifest["files"][source.name]:
                raise ValueError("native project changed while copying to scratch")
        board = scratch / board_name
        for _ in range(repeats):
            began = time.perf_counter()
            try:
                result = subprocess.run(  # nosec B603
                    [str(runtime), "-c", WORKER, str(board)],
                    cwd=scratch,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError("native KiCad load exceeded benchmark timeout") from exc
            except OSError as exc:
                raise RuntimeError("native KiCad inspect cannot execute") from exc
            if result.returncode != 0:
                raise RuntimeError("native KiCad inspect failed; cannot claim a benchmark")
            # Native libraries may write diagnostics to stdout; trust only
            # exactly one explicit protocol record, never the entire stream.
            markers = [
                line.removeprefix("KICAD_NATIVE_INSPECT_V1:")
                for line in result.stdout.splitlines()
                if line.startswith("KICAD_NATIVE_INSPECT_V1:")
            ]
            if len(markers) != 1:
                raise RuntimeError("native KiCad worker protocol is missing or ambiguous")
            try:
                observed = json.loads(markers[0])
            except (TypeError, ValueError) as exc:
                raise RuntimeError("native KiCad worker output is invalid") from exc
            if (
                not isinstance(observed, dict)
                or observed.get("footprints", 0) < int(manifest["minimum_pcb_footprints"])
                or not isinstance(observed.get("peak_rss_kib"), int)
                or observed["peak_rss_kib"] <= 0
                or any(
                    not isinstance(observed.get(key), (int, float)) or observed[key] < 0
                    for key in ("load_ms", "inspect_ms")
                )
            ):
                raise RuntimeError("native demo did not meet the verified size/metric floor")
            measurements.append(
                {
                    "footprints": observed["footprints"],
                    "tracks": observed["tracks"],
                    "copper_layers": observed["copper_layers"],
                    "kicad_build_version": observed["kicad_build_version"],
                    "load_ms": observed["load_ms"],
                    "inspect_ms": observed["inspect_ms"],
                    "process_peak_rss_kib": observed["peak_rss_kib"],
                    "wall_ms": round((time.perf_counter() - began) * 1000, 3),
                }
            )
    identities = {
        (row["footprints"], row["tracks"], row["copper_layers"], row["kicad_build_version"])
        for row in measurements
    }
    if len(identities) != 1:
        raise RuntimeError("native inspect produced inconsistent board identities")

    def metric(key: str) -> dict[str, float]:
        values = [float(row[key]) for row in measurements]
        return {
            "p50": round(statistics.median(values), 3),
            "p95_nearest_rank": round(nearest_rank_p95(values), 3),
        }

    return {
        "schema_version": SCHEMA,
        "repository_sha": repository_sha,
        "input_manifest_sha256": sha256_file(MANIFEST_PATH),
        "demo_id": manifest["demo_id"],
        "vendor_package": manifest["package"],
        "vendor_version": manifest["packaged_with_kicad_version"],
        "license": manifest["license"],
        "pcb_sha256": manifest["files"][board_name],
        "schematic_source_files": sum(path.suffix == ".kicad_sch" for path in sources),
        "platform": {"os": "linux", "architecture": platform.machine()},
        "run_count": repeats,
        "observations": measurements,
        "native_load_ms": metric("load_ms"),
        "native_inspect_ms": metric("inspect_ms"),
        "process_peak_rss_kib": metric("process_peak_rss_kib"),
        "status": "native_large_project_baseline_only",
        "not_measured": [
            "incremental mutation/update latency",
            "incremental graph/clean rebuild equivalence",
            "bounded refresh work units",
            "native ERC/DRC pass and manufacturing reproducibility",
            "agent task-success denominator",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-root", type=Path, default=DEFAULT_DEMO_ROOT)
    parser.add_argument("--python", type=Path, default=Path("/usr/bin/python3"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=100.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    git = shutil.which("git")
    if git is None:
        parser.error("git unavailable; source revision cannot be verified")
    resolved_git = Path(git).resolve(strict=True)
    if resolved_git not in (Path("/usr/bin/git"), Path("/usr/local/bin/git")):
        parser.error("git must be an OS-supplied executable")
    git_metadata = resolved_git.stat()
    if git_metadata.st_uid != 0 or git_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        parser.error("git executable is writable by untrusted users")
    source_sha = subprocess.run(  # nosec B603
        [str(resolved_git), "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    result = benchmark_demo(
        demo_root=args.demo_root,
        interpreter=args.python,
        repeats=args.repeats,
        timeout=args.timeout,
        repository_sha=source_sha,
    )
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        output = args.output.resolve()
        if output.is_relative_to(ROOT):
            parser.error("native benchmark evidence must be written outside checkout")
        try:
            with output.open("x", encoding="utf-8") as stream:
                stream.write(encoded)
        except FileExistsError:
            parser.error("cannot overwrite existing native benchmark evidence")
        print(f"Native large-project benchmark written to {output.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
