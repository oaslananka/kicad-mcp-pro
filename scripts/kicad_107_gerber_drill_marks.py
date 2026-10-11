#!/usr/bin/env python3
"""Qualify KiCad 10.0.7 Gerber non-plated drill-mark exclusion (#25532).

Native CLI is exercised with saved ``drillshape 2`` board options; NPTH holes
must not ink F.Cu while a real PTH pad still creates a valid flash. The NPTH
hole must remain present in its separate Excellon drill output. All generated
manufacturing-like outputs stay inside a disposable directory and are deleted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.kicad_canary import CanaryStep, _resolve_cli, _run_step
    from scripts.runtime_path_safety import approved_runtime_path
except ModuleNotFoundError:  # Direct `python scripts/foo.py` execution.
    from kicad_canary import CanaryStep, _resolve_cli, _run_step
    from runtime_path_safety import approved_runtime_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/kicad-10-0-7-drill-marks"
VERSION = "10.0.7"
CASES = {"npth": 0, "pth": 1}
FLASH = re.compile(r"D0*3\*")


class ProbeError(ValueError):
    """The native KiCad 10.0.7 Gerber drill-mark contract was not satisfied."""


def validate_gerbers(gerbers: dict[str, str], drill: str) -> dict[str, Any]:
    """Check actual Gerber flashes and that the NPTH drill file retains its hole."""
    if set(gerbers) != set(CASES):
        raise ProbeError("Expected NPTH and PTH independent Gerber controls")
    observed: dict[str, int] = {}
    for case, expected in CASES.items():
        text = gerbers[case]
        if "%FSLAX" not in text or "M02*" not in text:
            raise ProbeError(f"Malformed native F.Cu Gerber for {case}")
        count = len(FLASH.findall(text))
        if count != expected:
            raise ProbeError(f"Unexpected copper flash count for {case}: {count}")
        observed[case] = count
    if "TF.FileFunction,NonPlated" not in drill:
        raise ProbeError("Missing NPTH non-plated drill file identity")
    if "T1C3.200" not in drill or not re.search(r"(?m)^X50(?:\.0+)?Y-50(?:\.0+)?$", drill):
        raise ProbeError("NPTH 3.2-mm drill tool or known XY location missing")
    return {
        "schemaVersion": "kicad-107-gerber-drill-marks.v1",
        "kicadVersion": VERSION,
        "status": "pass",
        "savedDrillMarkStyle": "full",
        "copperFlashCount": observed,
        "npthDrillMm": 3.2,
        "npthLocationMm": {"x": 50, "y": 50},
    }


def _require_step(cli: Path, step: CanaryStep, workspace: Path) -> None:
    """Require the reviewed native runner to complete one expected operation."""
    result = _run_step(cli, step, workspace)
    if not result.get("ok") or result.get("returncode") != 0:
        raise ProbeError(f"Native KiCad step failed: {step.name}")


def _verify_version(cli: Path, workspace: Path) -> None:
    """Reject accidental fallback to any non-10.0.7 native installation."""
    _require_step(
        cli,
        CanaryStep(name="gerber-107-version", fixture="compatibility", args=("version",)),
        workspace,
    )
    actual = (workspace / "logs/gerber-107-version.stdout.log").read_text(encoding="utf-8")
    if actual.strip() != VERSION:
        raise ProbeError("Gerber drill-mark probe requires KiCad CLI 10.0.7")


def _export_copper(cli: Path, workspace: Path, case: str) -> str:
    """Plot one committed board from a private copy with its saved drill setting."""
    source = FIXTURES / f"{case}-stored-full-drill.kicad_pcb"
    text = source.read_text(encoding="utf-8")
    if "(drillshape 2)" not in text or "(at 50 50)" not in text:
        raise ProbeError(f"Unexpected stored Gerber plot settings for {case}")
    if f"{case} np_thru_hole" in text:
        raise ProbeError("Malformed fixture pad descriptor")
    if ("np_thru_hole" in text) != (case == "npth"):
        raise ProbeError(f"Incorrect PTH/NPTH fixture type for {case}")

    board_dir = workspace / case
    board_dir.mkdir()
    board = board_dir / source.name
    shutil.copyfile(source, board)
    output_dir = board_dir / "gerbers"
    output_dir.mkdir()
    gerber_file = output_dir / f"{case}-stored-full-drill-F_Cu.gbr"
    _require_step(
        cli,
        CanaryStep(
            name=f"gerber-{case}",
            fixture="drill-marks-107",
            args=(
                "pcb",
                "export",
                "gerbers",
                "--board-plot-params",
                "--output",
                str(output_dir),
                str(board),
            ),
            outputs=(gerber_file,),
        ),
        workspace,
    )
    return gerber_file.read_text(encoding="utf-8")


def _export_npth_drill(cli: Path, workspace: Path) -> str:
    """Independently confirm NPTH milling survives the Gerber exclusion."""
    drill_dir = workspace / "npth/drill"
    drill_dir.mkdir()
    board = workspace / "npth/npth-stored-full-drill.kicad_pcb"
    nc = drill_dir / "npth-stored-full-drill-NPTH.drl"
    _require_step(
        cli,
        CanaryStep(
            name="gerber-npth-excellon",
            fixture="drill-marks-107",
            args=(
                "pcb",
                "export",
                "drill",
                "--excellon-separate-th",
                "--output",
                str(drill_dir),
                str(board),
            ),
            outputs=(nc,),
        ),
        workspace,
    )
    return nc.read_text(encoding="utf-8")


def run_probe(cli: str) -> dict[str, Any]:
    """Validate both native Gerbers and NPTH drill using disposable copies."""
    snapshots = {
        case: hashlib.sha256(
            (FIXTURES / f"{case}-stored-full-drill.kicad_pcb").read_bytes()
        ).hexdigest()
        for case in CASES
    }
    with tempfile.TemporaryDirectory(prefix="kicad-107-gerber-drill-") as tmp:
        workspace = Path(tmp)
        native_cli = Path(cli)
        _verify_version(native_cli, workspace)
        gerbers = {case: _export_copper(native_cli, workspace, case) for case in CASES}
        report = validate_gerbers(gerbers, _export_npth_drill(native_cli, workspace))
    for case, digest in snapshots.items():
        source = FIXTURES / f"{case}-stored-full-drill.kicad_pcb"
        if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
            raise ProbeError("Read-only source fixture changed")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Path to bounded JSON report")
    args = parser.parse_args()
    report = run_probe(str(_resolve_cli()))
    report["sourceRevision"] = os.environ.get("SOURCE_REVISION", "")
    output = approved_runtime_path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        "KiCad 10.0.7 Gerber drill marks: 0 NPTH flashes, 1 PTH control flash, NPTH drill preserved"
    )


if __name__ == "__main__":
    main()
