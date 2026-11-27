"""Manufacturing release-evidence domain service and shared release-file helpers."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from ..path_safety import resolve_under

CliRunner = Callable[..., tuple[int, str, str]]


@dataclass(frozen=True)
class ReleaseEvidenceContext:
    """Runtime inputs needed to evaluate manufacturing release evidence."""

    output_dir: Path
    project_dir: Path | None
    project_file: Path | None
    pcb_file: Path | None
    sch_file: Path | None
    kicad_cli: Path
    kicad_cli_version: str | None
    kicad_mcp_version: str


def sha256_file(path: Path) -> str:
    """Return a stable SHA256 digest for ``path`` or ``unavailable`` on I/O failure."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        return "unavailable"
    return digest.hexdigest()


_REPORT_NAME = "manufacturing_release_report.json"
_EXPORT_LOCK = ".manufacturing-package-in-progress"


def _usable_artifact(path: Path, root: Path) -> bool:
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and path.stat().st_size > 0
            and path.resolve().is_relative_to(root.resolve())
        )
    except OSError:
        return False


def find_release_files(output_dir: Path) -> list[Path]:
    """Discover nonempty local files for legacy standalone release tools."""
    patterns = (
        "**/*.gbr",
        "**/*.drl",
        "**/*.xnc",
        "**/*.csv",
        "**/*.ipc",
        "**/*.ipc2581",
        "**/*.odb",
        "**/*.pos",
        "**/*.step",
        "**/*.xml",
        "**/*.pdf",
    )
    files = {path for pattern in patterns for path in output_dir.glob(pattern)}
    return sorted(path for path in files if _usable_artifact(path, output_dir))


def _verified_report_artifact(root: Path, item: object) -> Path:
    if not isinstance(item, dict):
        raise ValueError("Manufacturing report contains an invalid artifact record.")
    relative = item.get("relative_path")
    if not isinstance(relative, str) or not relative:
        raise ValueError("Manufacturing report contains an invalid artifact path.")
    spelling = PureWindowsPath(relative)
    if spelling.anchor or ".." in spelling.parts:
        raise ValueError("Manufacturing report contains an unsafe artifact path.")
    path = root.joinpath(*spelling.parts)
    if (
        not _usable_artifact(path, root)
        or type(item.get("size_bytes")) is not int
        or item["size_bytes"] != path.stat().st_size
        or item.get("sha256") != sha256_file(path)
        or item.get("sha256") == "unavailable"
    ):
        raise ValueError(f"Manufacturing report artifact is missing or changed: {relative}")
    return path


def verified_release_files(output_dir: Path) -> list[Path]:
    """Use the handoff's exact artifact hashes when it exists; never fall back on error."""
    lock = output_dir / _EXPORT_LOCK
    if lock.exists() or lock.is_symlink():
        raise ValueError("Manufacturing report unavailable: a package export is in progress.")
    report = output_dir / _REPORT_NAME
    if not report.exists() and not report.is_symlink():
        return find_release_files(output_dir)
    if report.is_symlink() or not report.is_file():
        raise ValueError("Manufacturing report is not a regular local file.")
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != "manufacturing_release.v1"
        ):
            raise ValueError("Manufacturing report has an invalid schema.")
        entries = payload.get("artifacts")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Manufacturing report has no artifact records.")
        files = [_verified_report_artifact(output_dir, item) for item in entries]
        if len(set(files)) != len(files):
            raise ValueError("Manufacturing report contains duplicate artifact paths.")
        return sorted(files)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manufacturing report could not be read or verified.") from exc


def _name_has_token(path: Path, *tokens: str) -> bool:
    name = path.name.casefold()
    return any(re.search(rf"(^|[-_.]){re.escape(token)}($|[-_.])", name) for token in tokens)


def _is_pick_and_place(path: Path) -> bool:
    suffix = path.suffix.casefold()
    parent = path.parent.name.casefold()
    if suffix == ".pos":
        return True
    if parent == "pos" and suffix in {".csv", ".gbr"}:
        return True
    return suffix in {".csv", ".gbr"} and _name_has_token(
        path, "pos", "cpl", "pick", "placement", "position"
    )


def _is_bom(path: Path) -> bool:
    return path.suffix.casefold() in {".csv", ".xml"} and _name_has_token(path, "bom")


def artifact_coverage(
    output_dir: Path,
    files: list[Path] | None = None,
) -> dict[str, list[Path]]:
    """Classify required manufacturing artifacts using disjoint reviewed filename rules."""
    if files is None:
        files = find_release_files(output_dir) if output_dir.exists() else []
    pick_and_place = [path for path in files if _is_pick_and_place(path)]
    pick_and_place_set = set(pick_and_place)
    return {
        "gerber": [
            path
            for path in files
            if path.suffix.casefold() == ".gbr" and path not in pick_and_place_set
        ],
        "drill": [path for path in files if path.suffix.casefold() in {".drl", ".xnc"}],
        "bom": [path for path in files if _is_bom(path)],
        "pick_and_place": pick_and_place,
    }


def build_release_file_hashes(
    release_files: list[Path],
    *,
    relative_to: Path | None = None,
) -> list[dict[str, str]]:
    """Return deterministic path/hash/size records for release files."""
    records: list[dict[str, str]] = []
    for path in release_files:
        try:
            size_bytes = str(path.stat().st_size)
        except OSError:
            size_bytes = "unavailable"
        if relative_to is None:
            filename = path.name
        else:
            try:
                filename = path.relative_to(relative_to).as_posix()
            except ValueError:
                filename = path.name
        records.append(
            {
                "filename": filename,
                "sha256": sha256_file(path),
                "size_bytes": size_bytes,
            }
        )
    return sorted(records, key=lambda entry: entry["filename"])


def _evidence_output_dir(context: ReleaseEvidenceContext, output_path: str) -> Path:
    if not output_path:
        return context.output_dir
    if context.project_dir is None:
        raise ValueError("A project directory is required when output_path is provided.")
    return resolve_under(context.project_dir, output_path)


def build_source_hashes(
    sources: list[tuple[str, Path | None]],
) -> dict[str, str]:
    """Hash configured source files while skipping absent paths."""
    return {
        label: sha256_file(path) for label, path in sources if path is not None and path.exists()
    }


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _evaluate_artifact_gate(
    artifact_dir: Path,
    release_files: list[Path],
    waive_missing_artifacts: bool,
) -> tuple[dict[str, Any], list[str]]:
    coverage = artifact_coverage(artifact_dir, files=release_files)
    found_artifacts = [name for name, matches in coverage.items() if matches]
    missing_artifacts = [name for name, matches in coverage.items() if not matches]

    artifact_passed = not missing_artifacts or waive_missing_artifacts
    gate = {
        "gate": "artifact_coverage",
        "passed": artifact_passed,
        "found": found_artifacts,
        "missing": missing_artifacts,
        "waived": waive_missing_artifacts and bool(missing_artifacts),
    }
    blocking: list[str] = []
    if not artifact_passed:
        blocking.append(
            f"Missing required artifacts: {', '.join(missing_artifacts)}. "
            "Run export_manufacturing_package() first."
        )
    return gate, blocking


def _report_entries(report: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Reject malformed finding lists instead of interpreting them as clean."""
    entries = report.get(key)
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"Invalid KiCad report field: {key}.")
    return entries


def _erc_violation_count(report: dict[str, Any]) -> int:
    """Count legacy flat findings and native per-sheet findings."""
    if "violations" not in report and "sheets" not in report:
        raise ValueError("ERC report contains no findings or sheets.")
    total = len(_report_entries(report, "violations")) if "violations" in report else 0
    if "sheets" in report:
        for sheet in _report_entries(report, "sheets"):
            total += len(_report_entries(sheet, "violations"))
    return total


def _run_cli_drc(
    run_cli: CliRunner,
    pcb_file: Path,
) -> tuple[bool, int, int, str | None]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, dir=pcb_file.parent) as tmp:
        tmp_path = tmp.name
    try:
        code, stdout, stderr = run_cli(
            "pcb",
            "drc",
            "--output",
            tmp_path,
            "--format",
            "json",
            "--schematic-parity",
            str(pcb_file),
        )
        if code == 0 and os.path.exists(tmp_path):
            report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            drc_violations = len(_report_entries(report, "violations"))
            if "schematic_parity" in report:
                drc_violations += len(_report_entries(report, "schematic_parity"))
            drc_unconnected = len(_report_entries(report, "unconnected_items"))
            drc_passed = drc_violations == 0 and drc_unconnected == 0
            return drc_passed, drc_violations, drc_unconnected, None
        return False, -1, -1, stderr or stdout or f"DRC exited with code {code}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _evaluate_drc_gate(
    run_cli: CliRunner,
    pcb_file: Path | None,
) -> tuple[dict[str, Any], list[str]]:
    drc_passed = False
    drc_violations = -1
    drc_unconnected = -1
    drc_error: str | None = None
    try:
        if pcb_file and pcb_file.exists():
            drc_passed, drc_violations, drc_unconnected, drc_error = _run_cli_drc(run_cli, pcb_file)
        else:
            drc_error = "No PCB file configured."
    except Exception as exc:  # preserve fail-closed release evidence behavior
        drc_error = str(exc)

    gate = {
        "gate": "drc",
        "passed": drc_passed,
        "violations": drc_violations,
        "unconnected_items": drc_unconnected,
        "error": drc_error,
    }
    blocking: list[str] = []
    if not drc_passed:
        if drc_error:
            blocking.append(f"DRC could not run: {drc_error}")
        else:
            blocking.append(
                f"DRC failed: {drc_violations} violation(s), {drc_unconnected} unconnected item(s)."
            )
    return gate, blocking


def _run_cli_erc(
    run_cli: CliRunner,
    sch_file: Path,
) -> tuple[bool, int, str | None]:
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, dir=sch_file.parent) as tmp:
        tmp_path = tmp.name
    try:
        code, stdout, stderr = run_cli(
            "sch",
            "erc",
            "--output",
            tmp_path,
            "--format",
            "json",
            str(sch_file),
        )
        if code == 0 and os.path.exists(tmp_path):
            report = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            erc_violations = _erc_violation_count(report)
            erc_passed = erc_violations == 0
            return erc_passed, erc_violations, None
        return False, -1, stderr or stdout or f"ERC exited with code {code}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _evaluate_erc_gate(
    run_cli: CliRunner,
    sch_file: Path | None,
) -> tuple[dict[str, Any], list[str]]:
    erc_passed = False
    erc_violations = -1
    erc_error: str | None = None
    try:
        if sch_file and sch_file.exists():
            erc_passed, erc_violations, erc_error = _run_cli_erc(run_cli, sch_file)
        else:
            erc_error = "No schematic file configured."
    except Exception as exc:  # preserve fail-closed release evidence behavior
        erc_error = str(exc)

    gate = {
        "gate": "erc",
        "passed": erc_passed,
        "violations": erc_violations,
        "error": erc_error,
    }
    blocking: list[str] = []
    if not erc_passed:
        if erc_error:
            blocking.append(f"ERC could not run: {erc_error}")
        else:
            blocking.append(f"ERC failed: {erc_violations} violation(s).")
    return gate, blocking


def _evaluate_hv_safety_gate(
    project_dir: Path | None,
    is_hv: bool,
    voltage_v: float,
    effective_domain: str,
) -> tuple[dict[str, Any], list[str]]:
    hv_gate_applicable = is_hv
    hv_gate_passed = True
    hv_gate_detail = "Not applicable (SELV domain)."
    if hv_gate_applicable:
        dru_files = list(project_dir.glob("*.kicad_dru")) if project_dir else []
        hv_dru: Path | None = None
        for dru in dru_files:
            text = dru.read_text(encoding="utf-8", errors="ignore")
            if "creepage" in text.lower() or "clearance" in text.lower():
                hv_dru = dru
                break
        if hv_dru:
            hv_gate_detail = f"HV design rules found in {hv_dru.name}."
        else:
            hv_gate_passed = False
            hv_gate_detail = (
                f"No .kicad_dru with creepage/clearance rules found for "
                f"{voltage_v:.0f} V {effective_domain} design. "
                "Run generate_board_constraints() to create HV safety rules."
            )
    gate = {
        "gate": "hv_safety",
        "applicable": hv_gate_applicable,
        "passed": hv_gate_passed,
        "detail": hv_gate_detail,
        "voltage_v": voltage_v,
        "domain": effective_domain,
    }
    blocking: list[str] = []
    if hv_gate_applicable and not hv_gate_passed:
        blocking.append(hv_gate_detail)
    return gate, blocking


@dataclass(frozen=True)
class ReleaseEvidenceService:
    """Evaluate manufacturing release gates independently of FastMCP transport."""

    run_cli: CliRunner
    now_utc: Callable[[], datetime] = _now_utc

    def create_evidence(
        self,
        *,
        context: ReleaseEvidenceContext,
        output_path: str = "",
        product_domain: str = "selv",
        voltage_v: float = 0.0,
        waive_missing_artifacts: bool = False,
        dry_run: bool = False,
    ) -> str:
        """Evaluate release gates and optionally write ``release_evidence.json``."""
        artifact_dir = context.output_dir
        evidence_dir = _evidence_output_dir(context, output_path)

        is_hv = product_domain == "hazardous_mains" or voltage_v > 60.0
        effective_domain = "hazardous_mains" if is_hv else "selv"

        gates: list[dict[str, Any]] = []
        blocking: list[str] = []

        try:
            release_files = verified_release_files(artifact_dir)
        except ValueError as exc:
            release_files = []
            blocking.append(str(exc))

        initial_hashes = build_release_file_hashes(release_files, relative_to=artifact_dir)
        artifact_gate, artifact_blocking = _evaluate_artifact_gate(
            artifact_dir, release_files, waive_missing_artifacts
        )
        gates.append(artifact_gate)
        blocking.extend(artifact_blocking)

        drc_gate, drc_blocking = _evaluate_drc_gate(self.run_cli, context.pcb_file)
        gates.append(drc_gate)
        blocking.extend(drc_blocking)

        erc_gate, erc_blocking = _evaluate_erc_gate(self.run_cli, context.sch_file)
        gates.append(erc_gate)
        blocking.extend(erc_blocking)

        hv_gate, hv_blocking = _evaluate_hv_safety_gate(
            context.project_dir, is_hv, voltage_v, effective_domain
        )
        gates.append(hv_gate)
        blocking.extend(hv_blocking)

        file_hashes = build_release_file_hashes(release_files, relative_to=artifact_dir)
        try:
            if (
                verified_release_files(artifact_dir) != release_files
                or file_hashes != initial_hashes
            ):
                blocking.append("Manufacturing artifacts changed during release validation.")
        except ValueError as exc:
            blocking.append(str(exc))
        if any("unavailable" in (item["sha256"], item["size_bytes"]) for item in file_hashes):
            blocking.append("Manufacturing artifact could not be hashed.")
        verdict = "release_approved" if not blocking else "release_blocked"
        source_hashes = build_source_hashes(
            [
                ("project", context.project_file),
                ("pcb", context.pcb_file),
                ("schematic", context.sch_file),
            ]
        )
        provenance: dict[str, Any] = {
            "kicad_mcp_version": context.kicad_mcp_version,
            "kicad_cli": str(context.kicad_cli),
            "kicad_cli_version": context.kicad_cli_version,
            "product_domain": effective_domain,
            "voltage_v": voltage_v,
            "source_hashes": source_hashes,
        }
        content_basis = json.dumps(
            {"files": file_hashes, "provenance": provenance, "gates": gates}, sort_keys=True
        )
        content_hash = hashlib.sha256(content_basis.encode()).hexdigest()

        evidence: dict[str, Any] = {
            "verdict": verdict,
            "generated_utc": self.now_utc().isoformat(),
            "content_hash": content_hash,
            "product_domain": effective_domain,
            "voltage_v": voltage_v,
            "gates": gates,
            "blocking_reasons": blocking,
            "provenance": provenance,
            "file_count": len(release_files),
            "files": file_hashes,
        }
        if dry_run:
            return json.dumps({**evidence, "dry_run": True, "evidence_path": None}, indent=2)

        evidence_dir.mkdir(parents=True, exist_ok=True)
        evidence_path = evidence_dir / "release_evidence.json"
        evidence_path.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        return json.dumps({**evidence, "evidence_path": str(evidence_path)}, indent=2)
