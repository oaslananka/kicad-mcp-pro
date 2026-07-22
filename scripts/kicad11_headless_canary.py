#!/usr/bin/env python3
"""Write separate KiCad 11 headless read, write, and export canary reports."""

from __future__ import annotations

import argparse
import inspect
import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

SURFACES = ("read", "write", "export")


@dataclass(frozen=True, slots=True)
class SurfaceReport:
    surface: str
    status: str
    kicad_version: str | None
    reason: str
    evidence: list[str]
    backend: str


def _report_payload(report: SurfaceReport) -> dict[str, object]:
    payload = asdict(report)
    payload["kicadVersion"] = payload.pop("kicad_version")
    return payload


def _write_report(artifacts: Path, report: SurfaceReport) -> None:
    target = artifacts / report.surface
    target.mkdir(parents=True, exist_ok=True)
    (target / "summary.json").write_text(
        json.dumps(_report_payload(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _run(command: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)


def _version(cli: Path) -> tuple[str | None, list[str]]:
    result = _run([str(cli), "version"])
    evidence = [f"kicad-cli version exit={result.returncode}"]
    if result.returncode != 0:
        return None, [*evidence, result.stderr.strip()]
    match = re.search(r"\b\d+\.\d+(?:\.\d+)?\b", f"{result.stdout}\n{result.stderr}")
    return (match.group(0) if match else None), evidence


def _major(version: str | None) -> int | None:
    if not version:
        return None
    match = re.match(r"(\d+)", version)
    return int(match.group(1)) if match else None


def _api_server_help(cli: Path) -> tuple[bool, list[str]]:
    result = _run([str(cli), "api-server", "--help"])
    text = f"{result.stdout}\n{result.stderr}"
    advertised = result.returncode == 0 and "api server" in text.casefold()
    return advertised, [
        f"kicad-cli api-server --help exit={result.returncode}",
        f"headless-api-advertised={str(advertised).lower()}",
    ]


def _headless_read_write(
    *,
    cli: Path,
    project_or_file: Path,
    version: str | None,
) -> tuple[SurfaceReport, SurfaceReport]:
    evidence: list[str] = []
    try:
        from kipy import KiCad
    except ImportError as exc:
        reason = f"kicad-python is unavailable: {exc}"
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return blocked, SurfaceReport("write", "blocked", version, reason, evidence, "unavailable")

    parameters = inspect.signature(KiCad.__init__).parameters
    required = {"headless", "kicad_cli_path", "file_path"}
    missing = sorted(required - set(parameters))
    if missing:
        reason = "Installed kicad-python does not expose headless construction: " + ", ".join(
            missing
        )
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return blocked, SurfaceReport("write", "blocked", version, reason, evidence, "unavailable")

    client: Any | None = None
    try:
        constructor = cast(Callable[..., Any], KiCad)
        active_client = constructor(
            headless=True,
            timeout_ms=10_000,
            kicad_cli_path=str(cli),
            file_path=str(project_or_file),
        )
        client = active_client
        connected_version = str(active_client.get_version())
        board = active_client.get_board()
        evidence.extend([f"connected-version={connected_version}", "board-open=true"])
        read = SurfaceReport(
            "read",
            "passed",
            version,
            "Headless IPC opened the fixture and returned a board handle.",
            list(evidence),
            "kicad-11-headless-ipc",
        )
        begin = getattr(board, "begin_commit", None)
        drop = getattr(board, "drop_commit", None)
        if callable(begin) and callable(drop):
            begin()
            drop()
            write = SurfaceReport(
                "write",
                "passed",
                version,
                "Headless IPC opened and discarded a no-op transaction without persisting changes.",
                [*evidence, "no-op-transaction=discarded"],
                "kicad-11-headless-ipc",
            )
        else:
            write = SurfaceReport(
                "write",
                "blocked",
                version,
                "The headless board API does not expose begin_commit/drop_commit.",
                list(evidence),
                "unavailable",
            )
        return read, write
    except Exception as exc:
        reason = f"Headless IPC probe failed: {type(exc).__name__}: {exc}"
        blocked = SurfaceReport("read", "blocked", version, reason, evidence, "unavailable")
        return blocked, SurfaceReport("write", "blocked", version, reason, evidence, "unavailable")
    finally:
        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                close()


def _export_report(
    *, cli: Path, project_or_file: Path, artifacts: Path, version: str | None
) -> SurfaceReport:
    output = artifacts / "export" / "board-stats.txt"
    output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            str(cli),
            "pcb",
            "export",
            "stats",
            "--output",
            str(output),
            str(project_or_file),
        ],
        timeout=180,
    )
    ok = result.returncode == 0 and output.exists() and output.stat().st_size > 0
    return SurfaceReport(
        "export",
        "passed" if ok else "blocked",
        version,
        (
            "KiCad CLI produced a non-empty board statistics artifact."
            if ok
            else f"KiCad CLI export smoke failed with exit code {result.returncode}."
        ),
        [f"kicad-cli pcb export stats exit={result.returncode}"],
        "kicad-cli" if ok else "unavailable",
    )


def run_canary(
    *,
    artifacts: Path,
    kicad_cli: Path | None,
    project_or_file: Path | None,
    require_ready: bool,
    unavailable_reason: str | None = None,
) -> int:
    """Run or report all three surfaces and optionally require native readiness."""
    artifacts.mkdir(parents=True, exist_ok=True)
    if kicad_cli is None or project_or_file is None:
        reason = unavailable_reason or "KiCad nightly CLI or fixture is unavailable."
        for surface in SURFACES:
            _write_report(
                artifacts,
                SurfaceReport(surface, "blocked", None, reason, [], "unavailable"),
            )
        return 1 if require_ready else 0

    version, version_evidence = _version(kicad_cli)
    api_advertised, api_evidence = _api_server_help(kicad_cli)
    major = _major(version)
    if major is None or major < 11 or not api_advertised:
        reason = (
            f"KiCad 11+ headless IPC is not ready (version={version!r}, "
            f"apiServerAdvertised={api_advertised})."
        )
        for surface in ("read", "write"):
            _write_report(
                artifacts,
                SurfaceReport(
                    surface,
                    "blocked",
                    version,
                    reason,
                    [*version_evidence, *api_evidence],
                    "unavailable",
                ),
            )
        export = _export_report(
            cli=kicad_cli,
            project_or_file=project_or_file,
            artifacts=artifacts,
            version=version,
        )
        _write_report(artifacts, export)
        return 1 if require_ready else 0

    read, write = _headless_read_write(
        cli=kicad_cli,
        project_or_file=project_or_file,
        version=version,
    )
    read = SurfaceReport(
        read.surface,
        read.status,
        read.kicad_version,
        read.reason,
        [*version_evidence, *api_evidence, *read.evidence],
        read.backend,
    )
    write = SurfaceReport(
        write.surface,
        write.status,
        write.kicad_version,
        write.reason,
        [*version_evidence, *api_evidence, *write.evidence],
        write.backend,
    )
    export = _export_report(
        cli=kicad_cli,
        project_or_file=project_or_file,
        artifacts=artifacts,
        version=version,
    )
    for report in (read, write, export):
        _write_report(artifacts, report)
    ready = all(report.status == "passed" for report in (read, write, export))
    return 0 if ready or not require_ready else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--kicad-cli", type=Path)
    parser.add_argument("--project-or-file", type=Path)
    parser.add_argument("--unavailable-reason")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)
    return run_canary(
        artifacts=args.artifacts,
        kicad_cli=args.kicad_cli,
        project_or_file=args.project_or_file,
        require_ready=args.require_ready,
        unavailable_reason=args.unavailable_reason,
    )


if __name__ == "__main__":
    raise SystemExit(main())
