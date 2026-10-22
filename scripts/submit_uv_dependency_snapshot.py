#!/usr/bin/env python3
"""Export the actual uv.lock resolution for GitHub's Dependency Submission API.

No network, token handling or package installation occurs here. Run on a
trusted main-branch workflow; the workflow uploads the JSON with gh api.
"""

from __future__ import annotations

import argparse
import json
import re
import tomllib
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def build_snapshot(
    lock_path: Path,
    *,
    sha: str,
    ref: str,
    job_id: str,
    scanned: str,
) -> dict[str, Any]:
    """Generate a full, accurate dependency snapshot, refusing unsafe inputs."""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("A full 40-digit commit SHA is required")
    if ref != "refs/heads/main":
        raise ValueError("Dependency submissions are restricted to refs/heads/main")
    lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages = lock["package"]
    versions = {
        _pypi_name(p["name"]): p["version"]
        for p in packages
        if p.get("source", {}).get("registry", "").startswith("https://pypi.org/")
    }
    if len(versions) != sum(
        p.get("source", {}).get("registry", "").startswith("https://pypi.org/") for p in packages
    ):
        raise ValueError("Multiple versions of a package require explicit PURL disambiguation")

    projects = [p for p in packages if p.get("source", {}).get("editable") == "."]
    if len(projects) != 1:
        raise ValueError("Expected one editable root project in uv.lock")
    project = projects[0]
    runtime_roots = {_pypi_name(p["name"]) for p in project.get("dependencies", [])}
    direct = set(runtime_roots)
    for deps in project.get("optional-dependencies", {}).values():
        direct.update(_pypi_name(dep["name"]) for dep in deps)
    for deps in project.get("dev-dependencies", {}).values():
        direct.update(_pypi_name(dep["name"]) for dep in deps)

    child_by_name: dict[str, set[str]] = defaultdict(set)
    for package in packages:
        key = _pypi_name(package["name"])
        child_by_name[key].update(
            _pypi_name(dep["name"]) for dep in package.get("dependencies", [])
        )
    runtime = set(runtime_roots)
    frontier = list(runtime_roots)
    while frontier:
        for child in child_by_name.get(frontier.pop(), ()):
            if child not in runtime:
                runtime.add(child)
                frontier.append(child)

    if not runtime_roots.issubset(versions):
        raise ValueError("Missing locked runtime dependencies")
    resolved = {}
    for name, version in sorted(versions.items()):
        children = sorted(
            f"pkg:pypi/{child}@{versions[child]}"
            for child in child_by_name[name]
            if child in versions
        )
        resolved[name] = {
            "package_url": f"pkg:pypi/{name}@{version}",
            "relationship": "direct" if name in direct else "indirect",
            "scope": "runtime" if name in runtime else "development",
            "dependencies": children,
        }
    if not resolved:
        raise ValueError("No PyPI dependencies in uv.lock")
    return {
        "version": 0,
        "sha": sha,
        "ref": ref,
        "job": {"id": job_id, "correlator": "main:uv-lock-dependency-submission"},
        "detector": {
            "name": "kicad-mcp-pro-uv-lock",
            "version": "1.0.0",
            "url": "https://github.com/oaslananka/kicad-mcp-pro/blob/main/scripts/submit_uv_dependency_snapshot.py",
        },
        "scanned": scanned,
        "manifests": {
            "uv.lock": {
                "name": "uv.lock",
                "file": {"source_location": "uv.lock"},
                "resolved": resolved,
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    scanned = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = build_snapshot(
        args.lock, sha=args.sha, ref=args.ref, job_id=args.job_id, scanned=scanned
    )
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
