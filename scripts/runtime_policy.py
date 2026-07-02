#!/usr/bin/env python3
"""Validate runtime support policy and report upstream version drift."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, TextIO

import yaml

MCP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = MCP_ROOT

VSCODE_STABLE_RELEASES_URL = "https://update.code.visualstudio.com/api/releases/stable"
VSCODE_INSIDER_RELEASES_URL = (
    "https://update.code.visualstudio.com/api/update/linux-x64/insider/latest"
)
PYTHON_RELEASES_URL = "https://peps.python.org/api/python-releases.json"
KICAD_LINUX_DOWNLOAD_URL = "https://www.kicad.org/download/linux/"
HTTP_HEADERS = {"User-Agent": "kicad-mcp-runtime-drift/1.0"}
GIT_EXECUTABLE = shutil.which("git") or "git"

DEFAULT_VSCODE_CHANGELOG = (
    Path("apps/vscode-extension/CHANGELOG.md")
    if (Path(__file__).resolve().parents[1] / "apps" / "vscode-extension").is_dir()
    else Path("CHANGELOG.md")
)
DEFAULT_MCP_CHANGELOG = Path("CHANGELOG.md")
SUPPORT_MATRIX_DOC = Path("docs/status/runtime-policy-matrix.md")


@dataclass(frozen=True, order=True)
class Version:
    """Normalized major.minor.patch version used for runtime policy comparisons."""

    major: int
    minor: int
    patch: int = 0

    @property
    def minor_key(self) -> str:
        return f"{self.major}.{self.minor}"

    def format(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class RuntimeSupportSnapshot:
    """Runtime support boundaries extracted from repo metadata."""

    vscode_engines_range: str
    python_requires: str
    kicad_primary: str
    kicad_supported_ranges: tuple[str, ...]
    python_supported_minors: tuple[str, ...] = ()
    kicad_latest_verified: str | None = None
    vscode_insiders_selector: str = "current"


@dataclass(frozen=True)
class DriftSourceVersions:
    """Current upstream versions fetched from official release sources."""

    vscode_stable: str
    vscode_insiders: str
    python_bugfix_minors: tuple[str, ...]
    kicad_stable: str
    source_errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimePolicyFinding:
    """One runtime support policy violation or drift signal."""

    surface: str
    severity: str
    message: str
    action: str


@dataclass(frozen=True)
class RuntimePolicyPaths:
    """Repository paths used by runtime support policy guards."""

    vscode_changelog: Path
    mcp_changelog: Path
    kicad_changelogs: tuple[Path, ...]
    support_matrix_doc: Path = SUPPORT_MATRIX_DOC


DEFAULT_RUNTIME_POLICY_PATHS = RuntimePolicyPaths(
    vscode_changelog=DEFAULT_VSCODE_CHANGELOG,
    mcp_changelog=DEFAULT_MCP_CHANGELOG,
    kicad_changelogs=(DEFAULT_VSCODE_CHANGELOG, DEFAULT_MCP_CHANGELOG),
)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_yaml_text(text: str, *, label: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise TypeError(f"{label} must contain a YAML mapping")
    return data


def _read_yaml(path: Path) -> dict[str, Any]:
    return _read_yaml_text(path.read_text(encoding="utf-8"), label=str(path))


def _read_toml_text(text: str) -> dict[str, Any]:
    return tomllib.loads(text)


def _read_pyproject(path: Path) -> dict[str, Any]:
    return _read_toml_text(path.read_text(encoding="utf-8"))


def _validated_https_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"Runtime policy fetches require https URLs, got {url!r}")
    return url


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(_validated_https_url(url), headers=HTTP_HEADERS)  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(_validated_https_url(url), headers=HTTP_HEADERS)  # noqa: S310
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def _parse_version(value: str) -> Version:
    match = re.search(r"(?P<major>\d+)\.(?P<minor>\d+)(?:\.(?P<patch>\d+))?", value)
    if match is None:
        raise ValueError(f"Cannot parse version from {value!r}")
    return Version(
        major=int(match.group("major")),
        minor=int(match.group("minor")),
        patch=int(match.group("patch") or 0),
    )


def _parse_vscode_engine_range(value: str) -> Version:
    if not value.startswith("^"):
        raise ValueError(f"VS Code engines.vscode must use a caret minimum range, got {value!r}")
    return _parse_version(value)


def _parse_python_requires(value: str) -> Version:
    match = re.search(r">=\s*(?P<version>\d+\.\d+(?:\.\d+)?)", value)
    if match is None:
        raise ValueError(f"Python requires-python must declare a >= lower bound, got {value!r}")
    return _parse_version(match.group("version"))


def _parse_kicad_range(value: str) -> Version:
    return _parse_version(value.replace(".x", ".0"))


def _runtime_policy(matrix: dict[str, Any]) -> dict[str, Any]:
    policy = matrix.get("runtimePolicy")
    if not isinstance(policy, dict):
        raise ValueError("compatibility.yaml missing runtimePolicy mapping")
    return policy


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    return value


def _required_str(mapping: dict[str, Any], key: str, *, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def _tuple_of_strings(values: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
        raise ValueError(f"{label} must be a list of strings")
    return tuple(values)


def _path_from_policy(
    policy: dict[str, Any],
    section: str,
    key: str,
    default: Path,
) -> Path:
    section_data = policy.get(section, {})
    if not isinstance(section_data, dict):
        raise ValueError(f"runtimePolicy.{section} must be a mapping")
    value = section_data.get(key, default.as_posix())
    if not isinstance(value, str) or not value:
        raise ValueError(f"runtimePolicy.{section}.{key} must be a non-empty string")
    return Path(value)


def _path_tuple_from_policy(
    policy: dict[str, Any],
    section: str,
    key: str,
    default: tuple[Path, ...],
) -> tuple[Path, ...]:
    section_data = policy.get(section, {})
    if not isinstance(section_data, dict):
        raise ValueError(f"runtimePolicy.{section} must be a mapping")
    value = section_data.get(key, [path.as_posix() for path in default])
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"runtimePolicy.{section}.{key} must be a list of non-empty strings")
    return tuple(Path(item) for item in value)


def _policy_paths(matrix: dict[str, Any]) -> RuntimePolicyPaths:
    policy = _runtime_policy(matrix)
    return RuntimePolicyPaths(
        vscode_changelog=_path_from_policy(
            policy,
            "vscode",
            "loweringRequiresChangelog",
            DEFAULT_VSCODE_CHANGELOG,
        ),
        mcp_changelog=_path_from_policy(
            policy,
            "python",
            "loweringRequiresChangelog",
            DEFAULT_MCP_CHANGELOG,
        ),
        kicad_changelogs=_path_tuple_from_policy(
            policy,
            "kicad",
            "loweringRequiresChangelogs",
            (DEFAULT_VSCODE_CHANGELOG, DEFAULT_MCP_CHANGELOG),
        ),
    )


def _snapshot_from_metadata(
    *,
    compatibility: dict[str, Any],
    extension_package: dict[str, Any],
    pyproject: dict[str, Any],
) -> RuntimeSupportSnapshot:
    kicad = _mapping(compatibility.get("kicad"), label="compatibility.kicad")
    python = _mapping(compatibility.get("python"), label="compatibility.python")
    vscode = _mapping(compatibility.get("vscode"), label="compatibility.vscode")
    extension_engines = _mapping(extension_package.get("engines"), label="extension.engines")
    pyproject_project = _mapping(pyproject.get("project"), label="pyproject.project")
    kicad_supported = kicad.get("supported")
    if not isinstance(kicad_supported, list) or not all(
        isinstance(entry, dict) and isinstance(entry.get("range"), str) for entry in kicad_supported
    ):
        raise ValueError("compatibility.kicad.supported must be a list of mappings with range")
    latest_verified = kicad.get("latestVerified")
    if latest_verified is not None and not isinstance(latest_verified, str):
        raise ValueError("compatibility.kicad.latestVerified must be a string")
    insiders_selector = vscode.get("insiders", "current")
    if not isinstance(insiders_selector, str) or not insiders_selector:
        raise ValueError("compatibility.vscode.insiders must be a non-empty string")
    return RuntimeSupportSnapshot(
        vscode_engines_range=_required_str(
            extension_engines,
            "vscode",
            label="extension.engines",
        ),
        python_requires=_required_str(
            pyproject_project,
            "requires-python",
            label="pyproject.project",
        ),
        kicad_primary=_required_str(kicad, "primary", label="compatibility.kicad"),
        kicad_supported_ranges=tuple(entry["range"] for entry in kicad_supported),
        python_supported_minors=_tuple_of_strings(
            python.get("supported"),
            label="python.supported",
        ),
        kicad_latest_verified=latest_verified,
        vscode_insiders_selector=insiders_selector,
    )


def _extension_package(root: Path) -> dict[str, Any]:
    """Read VS Code extension package.json, or return an empty fallback."""
    ext_path = root / "apps/vscode-extension/package.json"
    if ext_path.is_file():
        return _read_json(ext_path)
    return {"engines": {"vscode": "^0.0.0", "node": ">=0.0.0"}}


def snapshot_from_repo(root: Path = REPO_ROOT) -> RuntimeSupportSnapshot:
    """Build the current runtime support snapshot from repository files."""
    return _snapshot_from_metadata(
        compatibility=_read_yaml(root / "compatibility.yaml"),
        extension_package=_extension_package(root),
        pyproject=_read_pyproject(root / "pyproject.toml"),
    )


def _show_text(ref: str, path: Path) -> str:
    result = subprocess.run(
        [GIT_EXECUTABLE, "show", f"{ref}:{path.as_posix()}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _extension_package_from_git(ref: str) -> dict[str, Any]:
    """Read VS Code extension package.json from a git ref, or return an empty fallback."""
    try:
        return json.loads(_show_text(ref, Path("apps/vscode-extension/package.json")))
    except subprocess.CalledProcessError:
        return {"engines": {"vscode": "^0.0.0", "node": ">=0.0.0"}}


def snapshot_from_git_ref(ref: str) -> RuntimeSupportSnapshot:
    """Build a runtime support snapshot from files at a git ref."""
    compatibility = _read_yaml_text(
        _show_text(ref, Path("compatibility.yaml")), label="compatibility.yaml"
    )
    extension_package = _extension_package_from_git(ref)
    pyproject = _read_toml_text(_show_text(ref, Path("pyproject.toml")))
    return _snapshot_from_metadata(
        compatibility=compatibility,
        extension_package=extension_package,
        pyproject=pyproject,
    )


def _changed_files(base_ref: str) -> tuple[Path, ...]:
    result = subprocess.run(
        [GIT_EXECUTABLE, "diff", "--name-only", f"{base_ref}...HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(Path(line.strip()) for line in result.stdout.splitlines() if line.strip())


def _minor_window_from_requires(python_requires: str, window: int) -> tuple[str, ...]:
    lower = _parse_python_requires(python_requires)
    return tuple(f"{lower.major}.{lower.minor + offset}" for offset in range(window))


def validate_runtime_policy(root: Path = REPO_ROOT) -> list[str]:
    """Return local runtime policy metadata errors without remote release checks."""
    errors: list[str] = []
    matrix = _read_yaml(root / "compatibility.yaml")
    extension_package = _extension_package(root)
    pyproject = _read_pyproject(root / "pyproject.toml")

    try:
        policy = _runtime_policy(matrix)
    except ValueError as exc:
        return [str(exc)]

    snapshot = _snapshot_from_metadata(
        compatibility=matrix,
        extension_package=extension_package,
        pyproject=pyproject,
    )

    if (root / "apps" / "vscode-extension").is_dir():
        try:
            vscode_minimum = _parse_vscode_engine_range(snapshot.vscode_engines_range)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            if matrix["vscode"]["minimum"] != vscode_minimum.format():
                errors.append(
                    "VS Code minimum drift: "
                    f"compatibility.yaml={matrix['vscode']['minimum']!r}, "
                    f"engines.vscode={snapshot.vscode_engines_range!r}"
                )

    try:
        python_minimum = _parse_python_requires(snapshot.python_requires)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        if matrix["python"]["range"] != snapshot.python_requires:
            errors.append(
                "Python range drift: "
                f"compatibility.yaml={matrix['python']['range']!r}, "
                f"pyproject.toml={snapshot.python_requires!r}"
            )
        if snapshot.python_supported_minors:
            if snapshot.python_supported_minors[0] != python_minimum.minor_key:
                errors.append(
                    "Python supported window must start at requires-python lower bound: "
                    f"supported={snapshot.python_supported_minors!r}, "
                    f"requires-python={snapshot.python_requires!r}"
                )
            expected_size = int(policy.get("python", {}).get("supportedMinorWindow", 2))
            if len(snapshot.python_supported_minors) != expected_size:
                errors.append(
                    "Python supported window size drift: "
                    f"expected={expected_size}, actual={len(snapshot.python_supported_minors)}"
                )

    try:
        _parse_kicad_range(snapshot.kicad_primary)
        for supported in snapshot.kicad_supported_ranges:
            _parse_kicad_range(supported)
    except ValueError as exc:
        errors.append(str(exc))

    required_sources = {
        "vscodeStable": VSCODE_STABLE_RELEASES_URL,
        "vscodeInsiders": VSCODE_INSIDER_RELEASES_URL,
        "pythonReleases": PYTHON_RELEASES_URL,
        "kicadDownloads": KICAD_LINUX_DOWNLOAD_URL,
    }
    sources = policy.get("sources")
    if not isinstance(sources, dict):
        errors.append("runtimePolicy.sources must be a mapping")
    else:
        for key, expected in required_sources.items():
            if sources.get(key) != expected:
                errors.append(
                    f"runtimePolicy.sources.{key} must be {expected!r}, got {sources.get(key)!r}"
                )

    return errors


def _python_bugfix_minors_from_peps(data: dict[str, Any], window: int) -> tuple[str, ...]:
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Python releases feed missing metadata mapping")
    bugfix = [
        key
        for key, details in metadata.items()
        if isinstance(details, dict) and details.get("status") == "bugfix"
    ]
    bugfix.sort(key=_parse_version)
    return tuple(bugfix[-window:])


def _latest_vscode_release(data: object) -> str:
    if isinstance(data, dict):
        for key in ("name", "productVersion"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        raise ValueError("VS Code release metadata missing name/productVersion")
    if not isinstance(data, list) or not data:
        raise ValueError("VS Code release feed must be a non-empty JSON list")
    latest = data[0]
    if not isinstance(latest, str):
        raise ValueError("VS Code release feed entries must be strings")
    return latest


def _kicad_stable_from_download_page(text: str) -> str:
    match = re.search(
        r"Current Version:\s*(?:<strong>\s*)?([0-9]+(?:\.[0-9]+)+)",
        text,
    )
    if match is None:
        match = re.search(r"Current Version:\s*([0-9]+(?:\.[0-9]+)+)", text)
    if match is None:
        raise ValueError("Could not find KiCad current version on download page")
    return match.group(1)


def fetch_current_versions(python_supported_minor_window: int) -> DriftSourceVersions:
    """Fetch official current runtime versions for scheduled drift detection."""
    errors: list[str] = []

    try:
        vscode_stable = _latest_vscode_release(_fetch_json(VSCODE_STABLE_RELEASES_URL))
    except Exception as exc:  # noqa: BLE001 - preserve scheduled drift signal.
        vscode_stable = "unavailable"
        errors.append(f"VS Code stable release feed: {exc}")

    try:
        vscode_insiders = _latest_vscode_release(_fetch_json(VSCODE_INSIDER_RELEASES_URL))
    except Exception as exc:  # noqa: BLE001 - preserve scheduled drift signal.
        vscode_insiders = "unavailable"
        errors.append(f"VS Code insiders release feed: {exc}")

    try:
        python_bugfix_minors = _python_bugfix_minors_from_peps(
            _fetch_json(PYTHON_RELEASES_URL),
            python_supported_minor_window,
        )
    except Exception as exc:  # noqa: BLE001 - preserve scheduled drift signal.
        python_bugfix_minors = ()
        errors.append(f"Python releases feed: {exc}")

    try:
        kicad_stable = _kicad_stable_from_download_page(_fetch_text(KICAD_LINUX_DOWNLOAD_URL))
    except Exception as exc:  # noqa: BLE001 - preserve scheduled drift signal.
        kicad_stable = "unavailable"
        errors.append(f"KiCad download page: {exc}")

    return DriftSourceVersions(
        vscode_stable=vscode_stable,
        vscode_insiders=vscode_insiders,
        python_bugfix_minors=python_bugfix_minors,
        kicad_stable=kicad_stable,
        source_errors=tuple(errors),
    )


def detect_runtime_drift(
    *,
    snapshot: RuntimeSupportSnapshot,
    current: DriftSourceVersions,
    max_vscode_minor_lag: int,
    python_supported_minor_window: int,
) -> list[RuntimePolicyFinding]:
    """Return upstream runtime drift findings for a support snapshot."""
    findings: list[RuntimePolicyFinding] = []
    for error in current.source_errors:
        findings.append(
            RuntimePolicyFinding(
                surface="Runtime source",
                severity="warning",
                message=f"Could not read authoritative source: {error}.",
                action="Retry the workflow; if it persists, inspect source availability.",
            )
        )

    vscode_minimum = _parse_vscode_engine_range(snapshot.vscode_engines_range)
    if current.vscode_stable != "unavailable":
        vscode_stable = _parse_version(current.vscode_stable)
        vscode_lag = (vscode_stable.major - vscode_minimum.major) * 1000 + (
            vscode_stable.minor - vscode_minimum.minor
        )
        if vscode_lag > max_vscode_minor_lag:
            findings.append(
                RuntimePolicyFinding(
                    surface="VS Code",
                    severity="release-blocker",
                    message=(
                        "engines.vscode minimum "
                        f"{vscode_minimum.format()} is {vscode_lag} minor releases behind "
                        f"current stable {vscode_stable.format()}."
                    ),
                    action=(
                        "Raise apps/vscode-extension package engines.vscode, update "
                        "compatibility.yaml, docs/status/runtime-policy-matrix.md, and release notes."
                    ),
                )
            )

    if snapshot.vscode_insiders_selector != "current" and current.vscode_insiders != "unavailable":
        vscode_insiders = _parse_version(current.vscode_insiders)
        pinned_insiders = _parse_version(snapshot.vscode_insiders_selector)
        if vscode_insiders > pinned_insiders:
            findings.append(
                RuntimePolicyFinding(
                    surface="VS Code Insiders",
                    severity="warning",
                    message=(
                        f"VS Code insiders is pinned to {snapshot.vscode_insiders_selector}, "
                        f"but current insiders is {current.vscode_insiders}."
                    ),
                    action="Switch vscode.insiders back to current or document the pin.",
                )
            )

    supported_python = snapshot.python_supported_minors or _minor_window_from_requires(
        snapshot.python_requires,
        python_supported_minor_window,
    )
    expected_python = current.python_bugfix_minors[-python_supported_minor_window:]
    if expected_python and tuple(supported_python) != tuple(expected_python):
        findings.append(
            RuntimePolicyFinding(
                surface="Python",
                severity="warning",
                message=(
                    "Python support window is "
                    f"{', '.join(supported_python)} from {snapshot.python_requires}, "
                    f"but the current bugfix window is {', '.join(expected_python)}."
                ),
                action=(
                    "Validate the MCP server on the current Python bugfix window, then "
                    "update pyproject.toml, compatibility.yaml, and package classifiers."
                ),
            )
        )

    if current.kicad_stable != "unavailable":
        kicad_current = _parse_version(current.kicad_stable)
        kicad_primary = _parse_kicad_range(snapshot.kicad_primary)
        if (kicad_current.major, kicad_current.minor) != (
            kicad_primary.major,
            kicad_primary.minor,
        ):
            findings.append(
                RuntimePolicyFinding(
                    surface="KiCad",
                    severity="release-blocker",
                    message=(
                        f"KiCad primary range is {snapshot.kicad_primary}, "
                        f"but the official current release is {current.kicad_stable}."
                    ),
                    action=(
                        "Run KiCad canaries for the new primary line, update compatibility.yaml, "
                        "docs/status/runtime-policy-matrix.md, and migration notes."
                    ),
                )
            )
        elif snapshot.kicad_latest_verified is not None:
            latest_verified = _parse_version(snapshot.kicad_latest_verified)
            if kicad_current > latest_verified:
                findings.append(
                    RuntimePolicyFinding(
                        surface="KiCad",
                        severity="warning",
                        message=(
                            f"KiCad latestVerified is {snapshot.kicad_latest_verified}, "
                            f"but the official current release is {current.kicad_stable}."
                        ),
                        action=(
                            "Run the KiCad canary and update kicad.latestVerified after it passes."
                        ),
                    )
                )

    return findings


def _requires_file(changed_files: tuple[Path, ...], required: Path) -> bool:
    return required in changed_files


def detect_runtime_lowering(
    *,
    base: RuntimeSupportSnapshot,
    current: RuntimeSupportSnapshot,
    changed_files: tuple[Path, ...],
    policy_paths: RuntimePolicyPaths = DEFAULT_RUNTIME_POLICY_PATHS,
) -> list[RuntimePolicyFinding]:
    """Return PR guard findings when runtime minimums are lowered without changelog notes."""
    findings: list[RuntimePolicyFinding] = []
    base_vscode = _parse_vscode_engine_range(base.vscode_engines_range)
    current_vscode = _parse_vscode_engine_range(current.vscode_engines_range)
    if current_vscode < base_vscode and not _requires_file(
        changed_files,
        policy_paths.vscode_changelog,
    ):
        findings.append(
            RuntimePolicyFinding(
                surface="VS Code",
                severity="error",
                message=(
                    f"engines.vscode was lowered from {base.vscode_engines_range} "
                    "to "
                    f"{current.vscode_engines_range} without updating "
                    f"{policy_paths.vscode_changelog}."
                ),
                action="Add a dated deprecation/support note to the extension changelog.",
            )
        )

    base_python = _parse_python_requires(base.python_requires)
    current_python = _parse_python_requires(current.python_requires)
    if current_python < base_python and not _requires_file(
        changed_files, policy_paths.mcp_changelog
    ):
        findings.append(
            RuntimePolicyFinding(
                surface="Python",
                severity="error",
                message=(
                    f"requires-python was lowered from {base.python_requires} "
                    f"to {current.python_requires} without updating {policy_paths.mcp_changelog}."
                ),
                action="Add a dated deprecation/support note to the MCP server changelog.",
            )
        )

    base_kicad = _parse_kicad_range(base.kicad_primary)
    current_kicad = _parse_kicad_range(current.kicad_primary)
    missing_kicad_changelogs = tuple(
        path for path in policy_paths.kicad_changelogs if not _requires_file(changed_files, path)
    )
    if current_kicad < base_kicad and missing_kicad_changelogs:
        findings.append(
            RuntimePolicyFinding(
                surface="KiCad",
                severity="error",
                message=(
                    f"KiCad primary support was lowered from {base.kicad_primary} "
                    f"to {current.kicad_primary} without both product changelogs."
                ),
                action="Update both product changelogs with migration/support-drop context.",
            )
        )

    if findings or (base != current and not _requires_file(changed_files, SUPPORT_MATRIX_DOC)):
        if not _requires_file(changed_files, policy_paths.support_matrix_doc):
            findings.append(
                RuntimePolicyFinding(
                    surface="Support matrix",
                    severity="error",
                    message=(
                        "Runtime support metadata changed without updating "
                        f"{policy_paths.support_matrix_doc}."
                    ),
                    action="Update docs/status/runtime-policy-matrix.md in the same PR.",
                )
            )

    return findings


def _print_findings(title: str, findings: list[RuntimePolicyFinding], *, stream: TextIO) -> None:
    if not findings:
        print(f"{title}: passed.", file=stream)
        return
    print(f"{title} failed:", file=stream)
    for finding in findings:
        print(
            f"- [{finding.severity}] {finding.surface}: {finding.message} Action: {finding.action}",
            file=stream,
        )


def _findings_markdown(findings: list[RuntimePolicyFinding]) -> str:
    if not findings:
        return "Runtime support policy drift check passed. No drift was detected.\n"
    lines = [
        "# Runtime Support Policy Drift",
        "",
        "| Surface | Severity | Finding | Action |",
        "| --- | --- | --- | --- |",
    ]
    for finding in findings:
        lines.append(
            f"| {finding.surface} | {finding.severity} | {finding.message} | {finding.action} |"
        )
    lines.append("")
    return "\n".join(lines)


def _write_drift_outputs(
    *,
    findings: list[RuntimePolicyFinding],
    markdown_output: Path | None,
    json_output: Path | None,
) -> None:
    if markdown_output is not None:
        markdown_output.parent.mkdir(parents=True, exist_ok=True)
        markdown_output.write_text(_findings_markdown(findings), encoding="utf-8")
    if json_output is not None:
        json_output.parent.mkdir(parents=True, exist_ok=True)
        json_output.write_text(
            json.dumps(
                {"findings": [asdict(finding) for finding in findings]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )


def _policy_int(matrix: dict[str, Any], section: str, key: str, default: int) -> int:
    policy = _runtime_policy(matrix)
    value = policy.get(section, {}).get(key, default)
    if not isinstance(value, int):
        raise ValueError(f"runtimePolicy.{section}.{key} must be an integer")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check", help="Validate local runtime policy metadata.")

    drift_parser = subparsers.add_parser(
        "drift",
        help="Fetch official release sources and write drift findings.",
    )
    drift_parser.add_argument("--markdown-output", type=Path)
    drift_parser.add_argument("--json-output", type=Path)
    drift_parser.add_argument("--fail-on-drift", action="store_true")

    guard_parser = subparsers.add_parser(
        "guard-lowering",
        help="Block PRs that lower runtime support without changelog notes.",
    )
    guard_parser.add_argument("--base-ref", required=True)

    args = parser.parse_args(argv)

    if args.command == "check":
        errors = validate_runtime_policy()
        if errors:
            print("Runtime policy validation failed:", file=sys.stderr)
            for error in errors:
                print(f"- {error}", file=sys.stderr)
            return 1
        print("Runtime policy validation passed.")
        return 0

    if args.command == "drift":
        matrix = _read_yaml(REPO_ROOT / "compatibility.yaml")
        python_window = _policy_int(matrix, "python", "supportedMinorWindow", 2)
        findings = detect_runtime_drift(
            snapshot=snapshot_from_repo(),
            current=fetch_current_versions(python_window),
            max_vscode_minor_lag=_policy_int(matrix, "vscode", "maxMinimumMinorLag", 1),
            python_supported_minor_window=python_window,
        )
        _write_drift_outputs(
            findings=findings,
            markdown_output=args.markdown_output,
            json_output=args.json_output,
        )
        _print_findings("Runtime drift check", findings, stream=sys.stdout)
        if args.fail_on_drift and findings:
            return 1
        return 0

    if args.command == "guard-lowering":
        matrix = _read_yaml(REPO_ROOT / "compatibility.yaml")
        findings = detect_runtime_lowering(
            base=snapshot_from_git_ref(args.base_ref),
            current=snapshot_from_repo(),
            changed_files=_changed_files(args.base_ref),
            policy_paths=_policy_paths(matrix),
        )
        _print_findings("Runtime lowering guard", findings, stream=sys.stderr)
        return 1 if findings else 0

    parser.error(f"Unsupported command {args.command!r}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
