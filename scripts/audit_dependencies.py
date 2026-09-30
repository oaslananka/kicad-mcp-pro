"""Audit locked project dependencies without auditing the active venv bootstrap tools."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AcknowledgedAdvisory:
    package: str
    version: str
    advisory_id: str
    aliases: tuple[str, ...]
    rationale: str
    sources: tuple[str, ...]

    def matches(self, package: str, version: str, vuln_id: str, aliases: tuple[str, ...]) -> bool:
        return (
            package.lower() == self.package
            and version == self.version
            and (vuln_id == self.advisory_id or bool(set(aliases) & set(self.aliases)))
        )


ACKNOWLEDGED_ADVISORIES = (
    AcknowledgedAdvisory(
        package="markdown",
        version="3.10.2",
        advisory_id="PYSEC-2026-89",
        aliases=("CVE-2025-69534",),
        rationale=(
            "Python-Markdown 3.10.2 is the current PyPI release and is newer than "
            "the NVD/OSV fixed version 3.8.1; pip-audit currently reports no "
            "fix_versions for the advisory."
        ),
        sources=(
            "https://nvd.nist.gov/vuln/detail/CVE-2025-69534",
            "https://osv.dev/vulnerability/GHSA-5wmx-573v-2qwq",
            "https://pypi.org/project/Markdown/",
        ),
    ),
)


def _executable(name: str) -> str:
    resolved = which(name)
    if resolved is None:
        raise RuntimeError(f"Required executable not found on PATH: {name}")
    return resolved


def _run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603  # argv-only command.


def _run_audit(requirements: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603  # argv-only command.
        [
            _executable("uvx"),
            "--from",
            "pip-audit==2.10.0",
            "pip-audit",
            "-r",
            str(requirements),
            "--disable-pip",
            "--progress-spinner",
            "off",
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _iter_vulnerabilities(report: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    findings: list[tuple[str, str, dict[str, Any]]] = []
    for dependency in report.get("dependencies", []):
        package = str(dependency.get("name", "")).lower()
        version = str(dependency.get("version", ""))
        for vuln in dependency.get("vulns", []):
            findings.append((package, version, vuln))
    return findings


def _acknowledged(
    package: str,
    version: str,
    vuln_id: str,
    aliases: tuple[str, ...],
) -> AcknowledgedAdvisory | None:
    for advisory in ACKNOWLEDGED_ADVISORIES:
        if advisory.matches(package, version, vuln_id, aliases):
            return advisory
    return None


def _print_findings(
    acknowledged: list[tuple[str, str, dict[str, Any], AcknowledgedAdvisory]],
    unresolved: list[tuple[str, str, dict[str, Any]]],
) -> None:
    if acknowledged:
        print("Acknowledged pip-audit advisories with no local upgrade path:")
        for package, version, vuln, advisory in acknowledged:
            aliases = ", ".join(str(alias) for alias in vuln.get("aliases", [])) or "none"
            print(f"- {package} {version} {vuln.get('id')} (aliases: {aliases})")
            print(f"  rationale: {advisory.rationale}")
            print(f"  sources: {', '.join(advisory.sources)}")

    if unresolved:
        print("Unacknowledged pip-audit vulnerabilities:")
        for package, version, vuln in unresolved:
            fixes = ", ".join(str(fix) for fix in vuln.get("fix_versions", [])) or "none"
            aliases = ", ".join(str(alias) for alias in vuln.get("aliases", [])) or "none"
            print(f"- {package} {version} {vuln.get('id')} (aliases: {aliases}; fixes: {fixes})")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kicad-mcp-audit-") as tmp:
        requirements = Path(tmp) / "requirements.txt"
        _run(
            [
                _executable("uv"),
                "--quiet",
                "export",
                "--all-extras",
                "--frozen",
                "--format",
                "requirements.txt",
                "--no-emit-project",
                "--no-emit-package",
                "pip",
                "--output-file",
                str(requirements),
            ]
        )
        result = _run_audit(requirements)

    if not result.stdout.strip():
        if result.stderr:
            print(result.stderr.strip())
        return result.returncode or 1

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        print(result.stdout)
        if result.stderr:
            print(result.stderr.strip())
        return result.returncode or 1

    acknowledged: list[tuple[str, str, dict[str, Any], AcknowledgedAdvisory]] = []
    unresolved: list[tuple[str, str, dict[str, Any]]] = []
    for package, version, vuln in _iter_vulnerabilities(report):
        vuln_id = str(vuln.get("id", ""))
        aliases = tuple(str(alias) for alias in vuln.get("aliases", []))
        advisory = _acknowledged(package, version, vuln_id, aliases)
        if advisory is None:
            unresolved.append((package, version, vuln))
        else:
            acknowledged.append((package, version, vuln, advisory))

    _print_findings(acknowledged, unresolved)
    if unresolved:
        return 1

    if not acknowledged:
        print("No known vulnerabilities found by pip-audit.")
    else:
        print("No unacknowledged vulnerabilities found by pip-audit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
