#!/usr/bin/env python3
"""Validate release metadata consistency before release PRs are merged."""

from __future__ import annotations

import json
import os
import re
import sys
import tomllib
from pathlib import Path

from check_compatibility_matrix import validate_compatibility_matrix

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")
INIT_VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
CHANGELOG_VERSION_RE = re.compile(r"^## \[(?P<version>[^\]]+)\]", re.MULTILINE)
CHANGELOG_RELEASE_DATE_RE = re.compile(
    r"^## \[(?P<version>[^\]]+)\](?:\([^)]+\))?\s+"
    r"\((?P<date>\d{4}-\d{2}-\d{2})\)\s*$",
    re.MULTILINE,
)
CITATION_VERSION_RE = re.compile(
    r'^version:\s*["\']?(?P<version>[^"\'#\s]+)["\']?\s*(?:#.*)?$',
    re.MULTILINE,
)
CITATION_DATE_RE = re.compile(
    r'^date-released:\s*["\']?(?P<date>\d{4}-\d{2}-\d{2})["\']?'
    r"\s*(?P<comment>#.*)?$",
    re.MULTILINE,
)


def _read_json(path: str) -> dict[str, object]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _read_repo_json(path: str) -> dict[str, object]:
    return json.loads((REPO_ROOT / path).read_text(encoding="utf-8"))


def _project_version() -> str:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = data["project"]["version"]
    if not isinstance(version, str):
        raise TypeError("pyproject.toml project.version must be a string")
    return version


def _init_version() -> str:
    content = (ROOT / "src" / "kicad_mcp" / "__init__.py").read_text(encoding="utf-8")
    match = INIT_VERSION_RE.search(content)
    if match is None:
        raise ValueError("src/kicad_mcp/__init__.py does not expose __version__")
    return match.group(1)


def _collect_versions() -> dict[str, str]:
    server = _read_json("server.json")
    wrapper = _read_repo_json("packages/mcp-npm/package.json")
    manifest = _read_repo_json(".release-please-manifest.json")
    tauri_cargo = tomllib.loads(
        (REPO_ROOT / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    )
    tauri_config = _read_repo_json("src-tauri/tauri.conf.json")
    versions = {
        "pyproject.toml": _project_version(),
        "src/kicad_mcp/__init__.py": _init_version(),
        "server.json": str(server.get("version", "")),
        "packages/mcp-npm/package.json": str(wrapper.get("version", "")),
        ".release-please-manifest.json .": str(manifest.get(".", "")),
        ".release-please-manifest.json packages/mcp-npm": str(manifest.get("packages/mcp-npm", "")),
        "src-tauri/Cargo.toml": str(tauri_cargo.get("package", {}).get("version", "")),
        "src-tauri/tauri.conf.json": str(tauri_config.get("version", "")),
        ".release-please-manifest.json src-tauri": str(manifest.get("src-tauri", "")),
    }
    packages = server.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("server.json packages must be a non-empty list")
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise TypeError(f"server.json packages[{index}] must be an object")
        if "version" in package:
            versions[f"server.json packages[{index}]"] = str(package.get("version", ""))
    return versions


def _check_versions() -> list[str]:
    versions = _collect_versions()
    errors: list[str] = []
    for source, version in versions.items():
        if not VERSION_RE.match(version):
            errors.append(f"{source} has invalid semantic version: {version!r}")
    unique_versions = set(versions.values())
    if len(unique_versions) != 1:
        rendered = ", ".join(f"{source}={version}" for source, version in versions.items())
        errors.append(f"release metadata version drift detected: {rendered}")
    return errors


def _check_protocol_schema_version() -> list[str]:
    manifest = _read_repo_json(".release-please-manifest.json")
    package = _read_repo_json("packages/protocol-schemas/package.json")
    manifest_version = str(manifest.get("packages/protocol-schemas", ""))
    package_version = str(package.get("version", ""))
    errors: list[str] = []
    if not VERSION_RE.match(manifest_version):
        errors.append(
            ".release-please-manifest.json packages/protocol-schemas has invalid semantic "
            f"version: {manifest_version!r}"
        )
    if not VERSION_RE.match(package_version):
        errors.append(
            "packages/protocol-schemas/package.json has invalid semantic version: "
            f"{package_version!r}"
        )
    if manifest_version != package_version:
        errors.append(
            "protocol schema release metadata version drift detected: "
            f"manifest={manifest_version}, package={package_version}"
        )
    return errors


def _changelog_section(changelog: str, version: str) -> str:
    matches = list(CHANGELOG_VERSION_RE.finditer(changelog))
    for index, match in enumerate(matches):
        if match.group("version") != version:
            continue
        section_start = match.start()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(changelog)
        return changelog[section_start:section_end]
    return ""


def _check_citation(version: str) -> list[str]:
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    errors: list[str] = []

    version_match = CITATION_VERSION_RE.search(citation)
    if version_match is None:
        errors.append("CITATION.cff must declare a version")
    elif version_match.group("version") != version:
        errors.append(
            "CITATION.cff version drift detected: "
            f"citation={version_match.group('version')}, project={version}"
        )

    date_match = CITATION_DATE_RE.search(citation)
    if date_match is None:
        errors.append("CITATION.cff must declare date-released in YYYY-MM-DD format")
        return errors

    comment = date_match.group("comment") or ""
    if "x-release-please-date" not in comment:
        errors.append(
            "CITATION.cff date-released must include the x-release-please-date annotation"
        )

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    release_dates = {
        match.group("version"): match.group("date")
        for match in CHANGELOG_RELEASE_DATE_RE.finditer(changelog)
    }
    expected_date = release_dates.get(version)
    if expected_date is not None and date_match.group("date") != expected_date:
        errors.append(
            "CITATION.cff date-released does not match the current changelog release date: "
            f"citation={date_match.group('date')}, changelog={expected_date}"
        )
    return errors


def _check_changelog(version: str) -> list[str]:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    errors: list[str] = []

    if "## [Unreleased]" not in changelog:
        errors.append("CHANGELOG.md must retain an Unreleased section")

    # Release-please auto-generates CHANGELOG from git commit history and may
    # include old "Bump version to X.Y.Z" messages from past chore commits.
    # These are not human errors, so skip the noise check on release-please
    # branches. GITHUB_HEAD_REF is set by GitHub Actions on pull_request events.
    head_ref = os.environ.get("GITHUB_HEAD_REF", "")
    if (
        head_ref.startswith("release-please--")
        or os.environ.get("RELEASE_PLEASE_GENERATED_CHANGELOG") == "true"
    ):
        return errors

    current_section = _changelog_section(changelog, version)
    if not current_section:
        return errors

    noise_re = re.compile(
        rf"\bBump version to (?!{re.escape(version)}\b)\d+\.\d+\.\d+",
        re.IGNORECASE,
    )
    match = noise_re.search(current_section)
    if match is not None:
        errors.append(
            "CHANGELOG.md current release section contains stale release-please noise: "
            f"{match.group(0)!r}"
        )
    return errors


def main() -> int:
    version = _project_version()
    errors = [
        *_check_versions(),
        *_check_protocol_schema_version(),
        *_check_citation(version),
        *_check_changelog(version),
        *validate_compatibility_matrix(),
    ]
    if errors:
        print("Release preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Release preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
