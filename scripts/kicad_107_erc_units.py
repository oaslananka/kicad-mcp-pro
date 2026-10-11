#!/usr/bin/env python3
"""Fail-closed native KiCad 10.0.7 ERC JSON units regression (#25582).

The installed CLI is version-gated and a maintained schematic is copied into
an isolated temporary workspace. Source files are never modified. The only
persisted evidence is a bounded, source-path-free JSON summary.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

# Reuse the repository's already audited argv-only native canary runner.
# It enforces timeouts, checks native exit codes and records logs inside the
# disposable workspace. No new subprocess boundary or shell interpolation.
try:
    from scripts.kicad_canary import CanaryStep, _resolve_cli, _run_step
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from kicad_canary import CanaryStep, _resolve_cli, _run_step
    from runtime_path_safety import approved_runtime_path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = REPO_ROOT / "packages/kicad-fixtures/fixtures/erc-power-pin-error"
VERSION = "10.0.7"
VIOLATION_TYPE = "footprint_link_issues"
VIOLATION_SYMBOL = "J1"
EXPECTED_MM = {"x": 15.0, "y": 14.0}
UNIT_SCALE = {"mm": 1.0, "in": 1 / 25.4, "mils": 1000 / 25.4}
NATIVE_VIOLATION_EXIT = 5


class ProbeError(ValueError):
    """Native evidence cannot satisfy the bounded KiCad contract."""


def _observed_j1(report: dict[str, Any]) -> tuple[dict[str, float], int]:
    violations = [
        violation for sheet in report.get("sheets", []) for violation in sheet.get("violations", [])
    ]
    candidates = [
        item.get("pos")
        for violation in violations
        if violation.get("type") == VIOLATION_TYPE
        for item in violation.get("items", [])
        if "J1" in str(item.get("description", ""))
    ]
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise ProbeError("Expected one J1 footprint_link_issues diagnostic")
    try:
        position = {axis: float(candidates[0][axis]) for axis in ("x", "y")}
    except (KeyError, ValueError, TypeError) as exc:
        raise ProbeError("J1 coordinate is absent or not numeric") from exc
    if not all(math.isfinite(value) for value in position.values()):
        raise ProbeError("J1 coordinate is not finite")
    return position, len(violations)


def validate_reports(reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Check native JSON metadata, a known nonzero position, and exact unit scale."""
    if set(reports) != set(UNIT_SCALE):
        raise ProbeError("Missing or unexpected ERC unit reports")

    observed: dict[str, dict[str, Any]] = {}
    expected_count: int | None = None
    for unit, scale in UNIT_SCALE.items():
        report = reports[unit]
        if report.get("kicad_version") != VERSION:
            raise ProbeError(f"Unexpected KiCad version for {unit} ERC report")
        if report.get("coordinate_units") != unit:
            raise ProbeError(f"Unexpected coordinate units for {unit} ERC report")
        position, count = _observed_j1(report)
        if count == 0 or (expected_count is not None and count != expected_count):
            raise ProbeError(f"ERC violation count drift for {unit}")
        expected_count = count
        for axis in ("x", "y"):
            expected = EXPECTED_MM[axis] * scale
            if not math.isclose(position[axis], expected, rel_tol=0, abs_tol=0.001):
                raise ProbeError(
                    f"ERC JSON coordinate unit-scale mismatch for {unit}/{axis}: "
                    f"expected {expected}, observed {position[axis]}"
                )
        observed[unit] = {**position, "violationCount": count}

    return {
        "schemaVersion": "kicad-107-erc-json-units.v1",
        "kicadVersion": VERSION,
        "status": "pass",
        "diagnostic": VIOLATION_TYPE,
        "symbol": VIOLATION_SYMBOL,
        "units": observed,
    }


def run_probe(cli: str) -> dict[str, Any]:
    """Run exact-version CLI via the audited native runner in a temporary workspace."""
    reports: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="kicad-107-erc-units-") as temp:
        artifacts = Path(temp)
        version_result = _run_step(
            Path(cli),
            CanaryStep(name="kicad-107-version", fixture="compatibility", args=("version",)),
            artifacts,
        )
        if version_result.get("returncode") != 0 or not version_result.get("ok"):
            raise ProbeError("Unable to query native KiCad version")
        version = (artifacts / "logs/kicad-107-version.stdout.log").read_text(encoding="utf-8")
        if version.strip() != VERSION:
            raise ProbeError("Expected exact KiCad CLI version 10.0.7")

        workspace = artifacts / "fixture"
        shutil.copytree(FIXTURE, workspace)
        schematic = workspace / "erc-power-pin-error.kicad_sch"
        if not schematic.is_file():
            raise ProbeError("ERC regression schematic is missing")
        for unit in UNIT_SCALE:
            output = artifacts / f"erc-{unit}.json"
            step = CanaryStep(
                name=f"kicad-107-erc-{unit}",
                fixture="erc-power-pin-error",
                args=(
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--units",
                    unit,
                    "--exit-code-violations",
                    "--output",
                    str(output),
                    str(schematic),
                ),
                outputs=(output,),
                expects_violations=True,
            )
            result = _run_step(Path(cli), step, artifacts)
            if result.get("returncode") != NATIVE_VIOLATION_EXIT:
                raise ProbeError(f"Wrong ERC exit code for {unit}: {result.get('returncode')}")
            if not result.get("ok") or not output.is_file():
                raise ProbeError(f"Missing or invalid native ERC JSON report for {unit}")
            try:
                reports[unit] = json.loads(output.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ProbeError(f"Invalid native ERC JSON report for {unit}") from exc

    return validate_reports(reports)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Bounded JSON report destination")
    args = parser.parse_args()
    cli = _resolve_cli()
    result = run_probe(str(cli))
    result["sourceRevision"] = os.environ.get("SOURCE_REVISION", "")
    output = approved_runtime_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("KiCad 10.0.7 ERC JSON coordinate-unit regression passed for mm, in, mils")


if __name__ == "__main__":
    main()
