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

LOCK_FILENAME = "uv.lock"
LOCK_PATH = Path(__file__).resolve().parent.parent / LOCK_FILENAME
PYPI_REGISTRY = "https://pypi.org/"


def _pypi_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _locked_package_graph(
    packages: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, set[str]]]:
    versions: dict[str, str] = {}
    children: dict[str, set[str]] = defaultdict(set)
    registered_count = 0
    for package in packages:
        name = _pypi_name(package["name"])
        if package.get("source", {}).get("registry", "").startswith(PYPI_REGISTRY):
            registered_count += 1
            if name in versions:
                raise ValueError(
                    "Multiple versions of a package require explicit PURL disambiguation"
                )
            versions[name] = package["version"]
        children[name].update(
            _pypi_name(dependency["name"]) for dependency in package.get("dependencies", [])
        )
    if len(versions) != registered_count:
        raise ValueError("Incomplete PyPI package resolution")
    return versions, children


def _direct_roots(packages: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    projects = [package for package in packages if package.get("source", {}).get("editable") == "."]
    if len(projects) != 1:
        raise ValueError("Expected one editable root project in uv.lock")
    project = projects[0]
    runtime_roots = {_pypi_name(p["name"]) for p in project.get("dependencies", [])}
    direct = set(runtime_roots)
    for group in ("optional-dependencies", "dev-dependencies"):
        for dependencies in project.get(group, {}).values():
            direct.update(_pypi_name(dep["name"]) for dep in dependencies)
    return runtime_roots, direct


def _reachable_runtime(roots: set[str], children: dict[str, set[str]]) -> set[str]:
    runtime = set(roots)
    frontier = list(roots)
    while frontier:
        for child in children.get(frontier.pop(), ()):
            if child not in runtime:
                runtime.add(child)
                frontier.append(child)
    return runtime


def _resolved_packages(
    versions: dict[str, str],
    edges: dict[str, set[str]],
    direct: set[str],
    runtime: set[str],
) -> dict[str, dict[str, Any]]:
    resolved: dict[str, dict[str, Any]] = {}
    for name, version in sorted(versions.items()):
        resolved[name] = {
            "package_url": f"pkg:pypi/{name}@{version}",
            "relationship": "direct" if name in direct else "indirect",
            "scope": "runtime" if name in runtime else "development",
            "dependencies": sorted(
                f"pkg:pypi/{child}@{versions[child]}" for child in edges[name] if child in versions
            ),
        }
    if not resolved:
        raise ValueError("No PyPI dependencies in uv.lock")
    return resolved


def build_snapshot(
    *,
    sha: str,
    ref: str,
    job_id: str,
    scanned: str,
) -> dict[str, Any]:
    """Generate the dependency graph from this project's immutable lockfile path.

    CLI inputs control the verified GitHub run metadata only, never a file read
    or write destination. The fixed source is the repository's own uv.lock.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("A full 40-digit commit SHA is required")
    if ref != "refs/heads/main":
        raise ValueError("Dependency submissions are restricted to refs/heads/main")
    packages = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))["package"]
    versions, edges = _locked_package_graph(packages)
    runtime_roots, direct = _direct_roots(packages)
    if not runtime_roots.issubset(versions):
        raise ValueError("Missing locked runtime dependencies")
    runtime = _reachable_runtime(runtime_roots, edges)
    resolved = _resolved_packages(versions, edges, direct, runtime)
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
            LOCK_FILENAME: {
                "name": LOCK_FILENAME,
                "file": {"source_location": LOCK_FILENAME},
                "resolved": resolved,
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()
    scanned = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    result = build_snapshot(sha=args.sha, ref=args.ref, job_id=args.job_id, scanned=scanned)
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
