"""Run local workstation security scanners with clear missing-tool failures."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REQUIRED_COMMANDS = {
    "gitleaks": "Install gitleaks from https://github.com/gitleaks/gitleaks.",
    "actionlint": "Install actionlint from https://github.com/rhysd/actionlint.",
    "zizmor": "Install zizmor with `uv tool install zizmor`.",
}
OPTIONAL_COMMANDS = {
    "osv-scanner": "Install OSV Scanner from https://google.github.io/osv-scanner/.",
    "trivy": "Install Trivy from https://aquasecurity.github.io/trivy/.",
}


def _required_paths() -> dict[str, str]:
    """Return all required scanner paths, reporting every missing tool at once."""
    paths: dict[str, str] = {}
    missing: list[str] = []
    for command in REQUIRED_COMMANDS:
        path = _which(command)
        if path is None:
            missing.append(command)
        else:
            paths[command] = path
    if missing:
        for command in missing:
            print(f"{command} is required. {REQUIRED_COMMANDS[command]}", file=sys.stderr)
        raise SystemExit(127)
    return paths


def _require(command: str) -> str:
    path = _which(command)
    if path is None:
        print(f"{command} is required. {REQUIRED_COMMANDS[command]}", file=sys.stderr)
        raise SystemExit(127)
    return path


def _which(command: str) -> str | None:
    path = shutil.which(command)
    if path is not None:
        return path

    executable = f"{command}.exe" if sys.platform == "win32" else command
    for directory in (
        Path.home() / "go" / "bin",
        Path.home() / ".local" / "bin",
    ):
        candidate = directory / executable
        if candidate.is_file():
            return str(candidate)
    return None


def _run(command: list[str]) -> None:
    print("+ " + " ".join(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    required = _required_paths()
    _run([required["gitleaks"], "detect", "--no-banner", "--redact"])
    _run([required["actionlint"]])
    _run([required["zizmor"], "--offline", "--min-severity", "high", ".github/workflows"])

    osv = _which("osv-scanner")
    if osv is None:
        print(f"osv-scanner not found. {OPTIONAL_COMMANDS['osv-scanner']}")
    else:
        _run([osv, "scan", "source", "-r", "."])

    trivy = _which("trivy")
    if trivy is None:
        print(f"trivy not found. {OPTIONAL_COMMANDS['trivy']}")
    else:
        _run(
            [
                trivy,
                "fs",
                "--scanners",
                "vuln,secret,misconfig",
                "--severity",
                "HIGH,CRITICAL",
                "--exit-code",
                "1",
                "--ignore-unfixed",
                ".",
            ]
        )


if __name__ == "__main__":
    main()
