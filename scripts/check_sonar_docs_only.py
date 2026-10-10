"""Conservatively classify NUL-delimited Git diff paths for SonarCloud analysis.

Call with `git diff --no-renames --name-only -z`: source-to-doc renames
must retain the deleted source path, so no analyzed code change is skipped.
Malformed or empty data always requires a full scan.
"""

from __future__ import annotations

import argparse
from pathlib import Path


def is_docs_only_diff(raw: bytes) -> bool:
    if not raw or not raw.endswith(b"\0"):
        return False
    paths = raw[:-1].split(b"\0")
    return bool(paths) and all(path.startswith(b"docs/") and len(path) > 5 for path in paths)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths-file", type=Path, required=True)
    args = parser.parse_args()
    return 0 if is_docs_only_diff(args.paths_file.read_bytes()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
