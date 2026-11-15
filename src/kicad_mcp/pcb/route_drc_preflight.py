"""No-live-write native KiCad DRC preflight on isolated temporary PCB copies."""

from __future__ import annotations

import hashlib
import json
import math
import secrets
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

from ..routing.manual_tracks import TrackSpec
from ..validation.drc_report import (
    Report,
    connectivity_evidence_problems,
    evaluate_route_drc,
)
from ..validation.drc_runner import classify_drc_report


class RoutePreflightError(ValueError):
    """The offline DRC acceptance evidence is unavailable or not trustworthy."""


def _validate_specs(specs: list[TrackSpec]) -> None:
    if not 1 <= len(specs) <= 128:
        raise RoutePreflightError("Routing requires 1-128 segments")
    first = specs[0]
    if not first.net_name or not first.layer.endswith("_Cu"):
        raise RoutePreflightError("Candidate must specify a named net and copper layer")
    for spec in specs:
        numbers = (spec.x1_mm, spec.y1_mm, spec.x2_mm, spec.y2_mm, spec.width_mm)
        if not all(math.isfinite(value) for value in numbers):
            raise RoutePreflightError("Candidate contains non-finite geometry")
        if not 0 < spec.width_mm <= 5:
            raise RoutePreflightError("Candidate track width is invalid")
        if spec.net_name != first.net_name or spec.layer != first.layer:
            raise RoutePreflightError("Candidate must remain on one net and one copper layer")
        if spec.x1_mm == spec.x2_mm and spec.y1_mm == spec.y2_mm:
            raise RoutePreflightError("Zero-length copper segment refused")


def _run_drc(kicad_cli: Path, pcb_file: Path, report_file: Path) -> Report:
    command = [
        str(kicad_cli),
        "pcb",
        "drc",
        "--format",
        "json",
        "--output",
        str(report_file),
        str(pcb_file),
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RoutePreflightError("Native KiCad CLI DRC could not run") from exc
    if result.returncode != 0 or not report_file.is_file():
        raise RoutePreflightError("Native KiCad CLI DRC did not complete")
    try:
        parsed = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RoutePreflightError("Native DRC evidence cannot be parsed") from exc
    status, detail = classify_drc_report(parsed)
    if status not in ("clean", "findings"):
        raise RoutePreflightError(f"Native DRC evidence is invalid: {detail}")
    if problems := connectivity_evidence_problems(parsed):
        raise RoutePreflightError("Native DRC did not verify connectivity: " + "; ".join(problems))
    return cast(Report, parsed)


def _validate_native_custom_rule_loading(
    kicad_cli: Path,
    candidate_pcb: Path,
    rules_file: Path,
) -> None:
    """Prove KiCad compiled project custom rules, not merely exited zero.

    Append a deliberately failing width rule to the disposable candidate
    copy. KiCad may ignore a malformed .kicad_dru and return success.
    """
    marker = f"KICAD_MCP_RULE_LOAD_SENTINEL_{secrets.token_hex(8)}"
    sentinel = (
        f'\n(rule "{marker}"\n (constraint track_width (min 900.0000mm))\n (severity error))\n'
    )
    with rules_file.open("a", encoding="utf-8") as output:
        output.write(sentinel)
    report = _run_drc(
        kicad_cli,
        candidate_pcb,
        candidate_pcb.parent / "rules-probe.json",
    )
    violations = report.get("violations")
    if not isinstance(violations, list) or not any(
        isinstance(entry, dict)
        and entry.get("type") == "track_width"
        and marker in str(entry.get("description", ""))
        and entry.get("severity") == "error"
        for entry in violations
    ):
        raise RoutePreflightError(
            "Native KiCad custom rule loading could not be verified; "
            "unsafe to accept routing preflight"
        )


def run_route_drc_preflight(
    board_snapshot: str,
    segments: list[TrackSpec],
    *,
    project_file: Path,
    kicad_cli: Path,
) -> dict[str, bool | int]:
    """Run baseline and candidate DRC with KiCad's own CLI on disposable files.

    No user board, configuration or KiCad GUI is written or modified.
    Unknown native tooling, project rule context or DRC report refuses execution.
    """
    if not project_file.is_file() or project_file.suffix != ".kicad_pro":
        raise RoutePreflightError("Native project rules file is unavailable")
    if not kicad_cli.is_file():
        raise RoutePreflightError("Native KiCad CLI executable is unavailable")
    if not isinstance(board_snapshot, str) or not board_snapshot.startswith("(kicad_pcb"):
        raise RoutePreflightError("Native board snapshot is unavailable")
    _validate_specs(segments)
    python_name = "python.exe" if kicad_cli.suffix.lower() == ".exe" else "python3"
    native_python = kicad_cli.parent / python_name
    if not native_python.is_file():
        raise RoutePreflightError("KiCad-bundled Python with native PCB support is unavailable")
    helper = Path(__file__).with_name("offline_route_tracks.py")
    if not helper.is_file():
        raise RoutePreflightError("Native PCB candidate adapter is unavailable")
    custom_rules = project_file.with_suffix(".kicad_dru")
    if custom_rules.exists() and not custom_rules.is_file():
        raise RoutePreflightError("Custom native DRC rules path is invalid")
    evidence_files = [project_file]
    if custom_rules.is_file():
        evidence_files.append(custom_rules)
    source_hashes = {file: hashlib.sha256(file.read_bytes()).hexdigest() for file in evidence_files}

    with TemporaryDirectory(prefix="kicad-route-drc-") as workspace:
        root = Path(workspace)
        before = root / "baseline"
        after = root / "candidate"
        board_name = project_file.stem + ".kicad_pcb"
        for destination in (before, after):
            destination.mkdir()
            for evidence_file in evidence_files:
                shutil.copy2(evidence_file, destination / evidence_file.name)
            (destination / board_name).write_text(board_snapshot, encoding="utf-8")
        payload = root / "candidate_segments.json"
        payload.write_text(
            json.dumps(
                [
                    {
                        "x1_mm": spec.x1_mm,
                        "y1_mm": spec.y1_mm,
                        "x2_mm": spec.x2_mm,
                        "y2_mm": spec.y2_mm,
                        "width_mm": spec.width_mm,
                        "net_name": spec.net_name,
                        "layer": spec.layer,
                    }
                    for spec in segments
                ]
            ),
            encoding="utf-8",
        )
        try:
            result = subprocess.run(
                [
                    str(native_python),
                    str(helper),
                    str(before / board_name),
                    str(after / board_name),
                    str(payload),
                ],
                capture_output=True,
                text=True,
                timeout=35,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RoutePreflightError("KiCad native PCB candidate creation failed") from exc
        if result.returncode != 0:
            raise RoutePreflightError("KiCad native PCB candidate readback failed")
        baseline = _run_drc(kicad_cli, before / board_name, before / "report.json")
        candidate = _run_drc(kicad_cli, after / board_name, after / "report.json")
        if custom_rules.is_file():
            _validate_native_custom_rule_loading(
                kicad_cli,
                after / board_name,
                after / custom_rules.name,
            )
        for source, initial_hash in source_hashes.items():
            if hashlib.sha256(source.read_bytes()).hexdigest() != initial_hash:
                raise RoutePreflightError("Project DRC rules changed during preflight")
        return evaluate_route_drc(baseline, candidate)
