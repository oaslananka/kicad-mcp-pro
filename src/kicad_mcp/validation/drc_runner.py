"""Canonical KiCad PCB DRC execution and result classification."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, cast

from .drc_report import Report

DrcRunStatus = Literal["unavailable", "findings", "clean", "malformed"]
MALFORMED_DRC_PREFIX = "Malformed DRC report: "
RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]


class DrcCliCapabilities(Protocol):
    """KiCad CLI capability subset needed by the DRC runner."""

    @property
    def supports_drc_severity_all(self) -> bool: ...

    @property
    def supports_drc_exit_code_violations(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class DrcRunResult:
    """Typed outcome of one KiCad PCB DRC report execution."""

    path: Path
    status: DrcRunStatus
    report: Report | None
    return_code: int | None
    stderr: str
    error: str | None

    def as_legacy_tuple(self) -> tuple[Path, Report | None, str | None]:
        """Return the historical path/report/error shape used by tool callers."""
        if self.status in {"clean", "findings"}:
            return self.path, self.report, None
        if self.status == "malformed":
            detail = self.error or "unknown schema error"
            return self.path, None, f"{MALFORMED_DRC_PREFIX}{detail}"
        return self.path, None, self.error


def _validate_report_list(report: Report, key: str, *, required: bool = False) -> str | None:
    if key not in report:
        if required:
            return f"DRC report is missing required field '{key}'."
        return None
    raw = report[key]
    if not isinstance(raw, list):
        return f"DRC report field '{key}' must be a list."
    if any(not isinstance(entry, dict) for entry in raw):
        return f"DRC report field '{key}' must contain only objects."
    return None


def classify_drc_report(report: object) -> tuple[DrcRunStatus, str | None]:
    """Classify a parsed DRC report without conflating malformed data with clean data."""
    if not isinstance(report, dict):
        return "malformed", "DRC report root must be a JSON object."

    typed_report = cast(Report, report)
    for key, required in (
        ("violations", True),
        ("unconnected_items", False),
        ("items_not_passing_courtyard", False),
    ):
        if error := _validate_report_list(typed_report, key, required=required):
            return "malformed", error

    has_findings = any(
        bool(typed_report.get(key, []))
        for key in ("violations", "unconnected_items", "items_not_passing_courtyard")
    )
    return ("findings" if has_findings else "clean"), None


def classify_legacy_drc_result(
    report: Report | None,
    error: str | None,
) -> tuple[DrcRunStatus, str | None]:
    """Classify the historical path/report/error shape used by existing callers."""
    if report is not None:
        return classify_drc_report(report)
    if error and error.startswith(MALFORMED_DRC_PREFIX):
        return "malformed", error.removeprefix(MALFORMED_DRC_PREFIX)
    return "unavailable", error


def _command_variants(
    *,
    pcb_file: Path,
    report_path: Path,
    capabilities: DrcCliCapabilities,
) -> list[list[str]]:
    flags: list[str] = []
    if capabilities.supports_drc_severity_all:
        flags.append("--severity-all")
    if capabilities.supports_drc_exit_code_violations:
        flags.append("--exit-code-violations")
    return [
        [
            "pcb",
            "drc",
            "--output",
            str(report_path),
            "--format",
            "json",
            *flags,
            str(pcb_file),
        ],
        [
            "pcb",
            "drc",
            "--input",
            str(pcb_file),
            "--output",
            str(report_path),
            "--format",
            "json",
            *flags,
        ],
    ]


def _unavailable_error(return_code: int, stderr: str, *, report_missing: bool) -> str:
    detail = stderr.strip()
    if detail:
        return (
            detail
            if report_missing
            else f"DRC command failed with exit code {return_code}: {detail}"
        )
    if report_missing:
        return (
            f"DRC command failed with exit code {return_code} and did not produce a report."
            if return_code != 0
            else "DRC report was not produced."
        )
    return f"DRC command failed with exit code {return_code}."


def run_drc_report(
    report_name: str,
    *,
    pcb_file: Path,
    output_dir: Path,
    run_cli_variants: RunCliVariants,
    capabilities: DrcCliCapabilities,
) -> DrcRunResult:
    """Run one PCB DRC operation across supported CLI variants."""
    report_path = output_dir / report_name
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        report_path.unlink(missing_ok=True)
    except OSError as exc:
        return DrcRunResult(
            report_path,
            "unavailable",
            None,
            None,
            "",
            f"Could not prepare DRC report path: {exc}",
        )

    if not pcb_file.is_file():
        return DrcRunResult(
            report_path,
            "unavailable",
            None,
            None,
            "",
            "PCB input file is unavailable or does not exist.",
        )

    variants = _command_variants(
        pcb_file=pcb_file,
        report_path=report_path,
        capabilities=capabilities,
    )
    last_return_code: int | None = None
    last_stderr = ""
    last_error = "DRC report was not produced."

    for variant in variants:
        try:
            report_path.unlink(missing_ok=True)
        except OSError as exc:
            return DrcRunResult(
                report_path,
                "unavailable",
                None,
                last_return_code,
                last_stderr,
                f"Could not prepare DRC report path: {exc}",
            )

        try:
            return_code, _stdout, stderr = run_cli_variants([variant])
        except FileNotFoundError as exc:
            return DrcRunResult(report_path, "unavailable", None, None, "", str(exc))
        except subprocess.TimeoutExpired:
            return_code = 124
            stderr = "The kicad-cli command timed out."
        except OSError as exc:
            return DrcRunResult(report_path, "unavailable", None, None, "", str(exc))

        normalized_stderr = stderr.strip()
        last_return_code = return_code
        last_stderr = normalized_stderr
        if not report_path.is_file():
            last_error = _unavailable_error(
                return_code,
                normalized_stderr,
                report_missing=True,
            )
            continue

        try:
            parsed = json.loads(report_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            error = f"DRC report is not valid JSON: line {exc.lineno}, column {exc.colno}."
            return DrcRunResult(
                report_path,
                "malformed",
                None,
                return_code,
                normalized_stderr,
                error,
            )
        except OSError as exc:
            return DrcRunResult(
                report_path,
                "unavailable",
                None,
                return_code,
                normalized_stderr,
                f"Could not read DRC report: {exc}",
            )

        status, schema_error = classify_drc_report(parsed)
        report = cast(Report, parsed) if isinstance(parsed, dict) else None
        if status == "malformed":
            return DrcRunResult(
                report_path,
                status,
                report,
                return_code,
                normalized_stderr,
                schema_error,
            )
        if status == "findings":
            return DrcRunResult(
                report_path,
                status,
                report,
                return_code,
                normalized_stderr,
                None,
            )
        if return_code == 0:
            return DrcRunResult(
                report_path,
                "clean",
                report,
                return_code,
                normalized_stderr,
                None,
            )

        last_error = _unavailable_error(
            return_code,
            normalized_stderr,
            report_missing=False,
        )

    return DrcRunResult(
        report_path,
        "unavailable",
        None,
        last_return_code,
        last_stderr,
        last_error,
    )
