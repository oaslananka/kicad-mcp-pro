"""Combine same-run Windows native coverage with Linux full-suite coverage.

Windows-only code is real, security-critical source and must meet the unchanged
90% Python patch gate. We require SHA-bound, same-run build artifacts and merge
executed lines only; existing Linux data remains authoritative for everything
else. Never accept arbitrary paths or silently omit a missing native report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from coverage import Coverage

_SHA = re.compile(r"[a-f0-9]{40}\Z")
_WINDOWS_JSON = "windows-coverage.json"
_MANIFEST = "windows-coverage-manifest.json"


def _validated_report(root: Path, name: str) -> tuple[Path, bytes]:
    path = root / name
    if path.is_symlink() or not path.is_file() or path.resolve() != root.resolve() / name:
        raise ValueError(f"Missing or unsafe native coverage input: {name}")
    data = path.read_bytes()
    if not 1 <= len(data) <= 10_000_000:
        raise ValueError(f"Native coverage input size invalid: {name}")
    return path, data


def _source_sha(root: Path, sha: str) -> None:
    if not _SHA.fullmatch(sha):
        raise ValueError("Expected full Git commit hash")
    git_executable = shutil.which("git")
    if git_executable is None:
        raise ValueError("Git is required for coverage provenance")
    actual = subprocess.check_output(
        [git_executable, "rev-parse", "HEAD"], cwd=root, text=True, timeout=10
    ).strip()
    if actual != sha:
        raise ValueError("Coverage commit does not match the checked-out commit")


def stamp_windows_report(root: Path, sha: str, run_id: int, attempt: int) -> None:
    """Stamp generated coverage with SHA and same-run provenance."""
    _source_sha(root, sha)
    if run_id <= 0 or attempt <= 0:
        raise ValueError("Invalid workflow run identity")
    _, blob = _validated_report(root, _WINDOWS_JSON)
    report = json.loads(blob)
    if not isinstance(report.get("files"), dict) or not report["files"]:
        raise ValueError("Empty or invalid native coverage report")
    manifest = {
        "version": 1,
        "sha": sha,
        "run_id": run_id,
        "attempt": attempt,
        "coverage_sha256": hashlib.sha256(blob).hexdigest(),
    }
    (root / _MANIFEST).write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")


def _validated_source_hits(
    root: Path, raw_path: str, details: dict, measured: dict[Path, str]
) -> tuple[str, set[int]]:
    """Verify that only existing, measured in-package source lines are merged."""
    path = raw_path.replace("\\", "/")
    posix = PurePosixPath(path)
    if (
        not path.startswith("src/kicad_mcp/")
        or posix.is_absolute()
        or ".." in posix.parts
        or posix.suffix != ".py"
    ):
        raise ValueError("Windows report contains a non-package or unsafe path")
    source = (root / path).resolve(strict=True)
    if not source.is_relative_to(root.resolve()):
        raise ValueError("Native coverage path escaped repository")
    canonical = measured.get(source)
    if canonical is None:
        raise ValueError(f"Windows source was not measured by Linux: {path}")
    values = details.get("executed_lines")
    if (
        not isinstance(values, list)
        or any(type(n) is not int or n < 1 for n in values)
        or any(n > len(source.read_text(encoding="utf-8").splitlines()) for n in values)
    ):
        raise ValueError(f"Invalid executed line numbers in native coverage: {path}")
    return canonical, set(values)


def merge_native_coverage(root: Path, sha: str, run_id: int, attempt: int) -> int:
    """Merge executed lines into existing full-suite coverage without exclusions."""
    _source_sha(root, sha)
    _, blob = _validated_report(root, _WINDOWS_JSON)
    _, manifest_bytes = _validated_report(root, _MANIFEST)
    manifest = json.loads(manifest_bytes)
    expected = {
        "version": 1,
        "sha": sha,
        "run_id": run_id,
        "attempt": attempt,
        "coverage_sha256": hashlib.sha256(blob).hexdigest(),
    }
    if manifest != expected:
        raise ValueError("Native coverage artifact is stale, altered or cross-run")
    report = json.loads(blob)
    files = report.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Native coverage file list is empty")

    coverage_data = root / ".coverage"
    if coverage_data.is_symlink() or not coverage_data.is_file():
        raise ValueError("Missing Linux full-suite coverage database")
    cov = Coverage(data_file=str(coverage_data))
    cov.load()
    data = cov.get_data()
    if data.has_arcs():
        raise ValueError("Cannot mix branch and line coverage data")
    measured = {Path(p).resolve(): p for p in data.measured_files()}
    hits: dict[str, set[int]] = {}
    for raw_path, details in files.items():
        if not isinstance(raw_path, str) or not isinstance(details, dict):
            raise ValueError("Invalid Windows coverage file entry")
        canonical, values = _validated_source_hits(root, raw_path, details, measured)
        hits[canonical] = values
    if not hits:
        raise ValueError("No Windows execution evidence in coverage report")

    data.add_lines(hits)
    cov.save()
    cov.json_report(outfile=str(root / "coverage.json"))
    cov.xml_report(outfile=str(root / "coverage.xml"))
    return sum(len(v) for v in hits.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stamp", "merge"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    if args.action == "stamp":
        stamp_windows_report(root, args.sha, args.run_id, args.attempt)
        print("Native coverage artifact stamped for this exact CI run")
    else:
        total = merge_native_coverage(root, args.sha, args.run_id, args.attempt)
        print(f"Native coverage merged: {total} executed source lines")


if __name__ == "__main__":
    main()
