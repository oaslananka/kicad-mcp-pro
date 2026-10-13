"""Create and verify same-workflow coverage artifacts using immutable run identity.

The artifact is an *internal* report hand-off, not an authorization token. Both
producer and consumer must belong to one GitHub Actions workflow run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

COVERAGE_FILE = Path("coverage.xml")
MANIFEST_FILE = Path("ci-coverage-manifest.json")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Coverage artifact must be a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_for(*, sha: str, run_id: int, attempt: int) -> dict[str, str | int]:
    if not COMMIT_RE.fullmatch(sha) or run_id < 1 or attempt < 1:
        raise ValueError("Invalid coverage run identity")
    return {
        "schema_version": 1,
        "commit": sha,
        "run_id": run_id,
        "attempt": attempt,
        "coverage_sha256": _sha256(COVERAGE_FILE),
    }


def write_manifest(*, sha: str, run_id: int, attempt: int) -> None:
    if MANIFEST_FILE.is_symlink():
        raise ValueError("Coverage manifest cannot be a symlink")
    data = manifest_for(sha=sha, run_id=run_id, attempt=attempt)
    MANIFEST_FILE.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def verify_manifest(*, sha: str, run_id: int, attempt: int) -> None:
    if MANIFEST_FILE.is_symlink() or not MANIFEST_FILE.is_file():
        raise ValueError("Coverage manifest must be a regular file")
    expected = manifest_for(sha=sha, run_id=run_id, attempt=attempt)
    received = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    if received != expected:
        raise ValueError("Coverage report is missing, tampered with, or from a different run")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("create", "verify"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--run-id", required=True, type=int)
    parser.add_argument("--attempt", required=True, type=int)
    args = parser.parse_args()
    try:
        if args.operation == "create":
            write_manifest(sha=args.sha, run_id=args.run_id, attempt=args.attempt)
        else:
            verify_manifest(sha=args.sha, run_id=args.run_id, attempt=args.attempt)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"coverage identity check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
