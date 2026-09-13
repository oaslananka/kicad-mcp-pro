"""Benchmark-only MCP server for reference-board manufacturing reproducibility."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, cast

from ..config import get_config, reset_config
from ..discovery import get_cli_capabilities
from ..export.bom import ExportBomService
from ..export.drill import ExportDrillService
from ..export.gerber import ExportGerberService
from ..server import KiCadFastMCP, _ensure_thread_aware_stdout, build_server
from ..tools.export import (
    _active_variant_args,
    _bom_project_schematic_files,
    _bom_schematic_component_rows,
    _format_file_list,
)
from ..tools.export_support import _get_pcb_file, _get_sch_file, _run_cli_variants

ReferenceSnapshotGeneration = Literal["generation-1", "generation-2"]

_REFERENCE_SNAPSHOT_PARENT = "reference-manufacturing"
_REFERENCE_MANIFEST_FILE = "artifact-manifest.json"
_REFERENCE_COMPARISON_FILE = "comparison.json"
REFERENCE_MANUFACTURING_NORMALIZATION_RULES_VERSION = "kicad-cli-timestamps-v1"

_GERBER_CREATION_DATE_RE = re.compile(rb"^%TF\.CreationDate,[^\r\n]*\*%$")
_GERBER_CREATED_BY_PREFIX = b"G04 Created by KiCad (PCBNEW "
_DRILL_CREATED_BY_PREFIX = b"; DRILL file KiCad "
_CREATED_BY_DATE_SEPARATOR = b" date "
_DRILL_CREATION_DATE_RE = re.compile(rb"^; #@! TF\.CreationDate,[^\r\n]*$")
_GBRJOB_CREATION_DATE_FIELD_RE = re.compile(rb"(\"CreationDate\"\s*:\s*\")[^\"\r\n]+(\")")


REFERENCE_MANUFACTURING_TOOL_NAMES: tuple[str, ...] = (
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_get_version",
    "kicad_get_server_info",
    "project_get_design_spec",
    "pcb_get_board_summary",
    "pcb_get_design_rules",
    "pcb_get_stackup",
    "validate_design",
    "run_drc",
    "run_erc",
    "validate_footprints_vs_schematic",
    "check_design_for_manufacture",
    "dfm_run_manufacturer_check",
    "project_quality_gate",
    "manufacturing_quality_gate",
    "get_board_stats",
    "reference_generate_manufacturing_snapshot",
    "reference_compare_manufacturing_snapshots",
)


def _reference_snapshot_root(generation: ReferenceSnapshotGeneration) -> Path:
    if generation not in ("generation-1", "generation-2"):
        raise ValueError("reference manufacturing generation is invalid")
    parent = get_config().ensure_output_dir(_REFERENCE_SNAPSHOT_PARENT)
    return parent / generation


def _snapshot_subdir(root: Path, subdir: str | None) -> Path:
    if subdir not in (None, "Gerbers"):
        raise ValueError("reference manufacturing snapshot output subdirectory is invalid")
    target = root if subdir is None else root / subdir
    target.mkdir(parents=True, exist_ok=True)
    return target


def _snapshot_export_services(root: Path) -> SimpleNamespace:
    cfg = get_config()
    gerber = ExportGerberService(
        get_pcb_file=_get_pcb_file,
        ensure_output_dir=lambda subdir: _snapshot_subdir(root, subdir),
        get_gerber_command=lambda: get_cli_capabilities(cfg.kicad_cli).gerber_command,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )
    drill = ExportDrillService(
        get_pcb_file=_get_pcb_file,
        ensure_output_dir=lambda subdir: _snapshot_subdir(root, subdir),
        get_drill_command=lambda: get_cli_capabilities(cfg.kicad_cli).drill_command,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )
    bom = ExportBomService(
        get_sch_file=_get_sch_file,
        ensure_output_dir=lambda: _snapshot_subdir(root, None),
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        read_preview=lambda _path: "",
        project_schematic_files=_bom_project_schematic_files,
        schematic_component_rows=_bom_schematic_component_rows,
    )
    return SimpleNamespace(gerber=gerber, drill=drill, bom=bom)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _snapshot_file_entries(root: Path) -> list[dict[str, str | int]]:
    entries: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.name == _REFERENCE_MANIFEST_FILE:
            continue
        if path.is_symlink():
            raise ValueError("reference manufacturing snapshot must not contain symlinks")
        if not path.is_file():
            continue
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256_path(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return entries


def _manifest_digest(entries: list[dict[str, str | int]]) -> str:
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(str(entry["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return f"sha256:{digest.hexdigest()}"


def _normalize_gbrjob_creation_date(data: bytes) -> bytes:
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data
    if not isinstance(payload, dict):
        return data
    header = payload.get("Header")
    if not isinstance(header, dict):
        return data
    creation_date = header.get("CreationDate")
    software = header.get("GenerationSoftware")
    if not isinstance(creation_date, str) or not isinstance(software, dict):
        return data
    vendor = software.get("Vendor")
    if not isinstance(vendor, str) or vendor.casefold() != "kicad":
        return data
    matches = tuple(_GBRJOB_CREATION_DATE_FIELD_RE.finditer(data))
    if len(matches) != 1:
        return data
    match = matches[0]
    return (
        data[: match.start()]
        + match.group(1)
        + b"<normalized-kicad-creation-date>"
        + match.group(2)
        + data[match.end() :]
    )


def _line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    return b""


def _is_single_line(body: bytes) -> bool:
    return b"\r" not in body and b"\n" not in body


def _is_gerber_created_by_line(body: bytes) -> bool:
    if not _is_single_line(body) or not body.startswith(_GERBER_CREATED_BY_PREFIX):
        return False
    if not body.endswith(b"*"):
        return False
    return b") date " in body[len(_GERBER_CREATED_BY_PREFIX) : -1]


def _is_drill_created_by_line(body: bytes) -> bool:
    if not _is_single_line(body) or not body.startswith(_DRILL_CREATED_BY_PREFIX):
        return False
    return _CREATED_BY_DATE_SEPARATOR in body[len(_DRILL_CREATED_BY_PREFIX) :]


def _normalize_kicad_generated_line(
    body: bytes, *, is_kicad_gerber: bool, is_kicad_drill: bool
) -> bytes:
    if is_kicad_gerber and _GERBER_CREATION_DATE_RE.fullmatch(body):
        return b"%TF.CreationDate,<normalized>*%"
    if is_kicad_gerber and _is_gerber_created_by_line(body):
        return body.rsplit(_CREATED_BY_DATE_SEPARATOR, 1)[0] + b" date <normalized>*"
    if is_kicad_drill and _is_drill_created_by_line(body):
        return body.rsplit(_CREATED_BY_DATE_SEPARATOR, 1)[0] + b" date <normalized>"
    if is_kicad_drill and _DRILL_CREATION_DATE_RE.fullmatch(body):
        return b"; #@! TF.CreationDate,<normalized>"
    return body


def _normalize_kicad_timestamp_bytes(relative: str, data: bytes) -> bytes:
    """Normalize only KiCad-generated timestamp metadata for comparison."""
    if Path(relative).suffix.casefold() == ".gbrjob":
        return _normalize_gbrjob_creation_date(data)

    is_kicad_gerber = b"%TF.GenerationSoftware,KiCad," in data
    is_kicad_drill = (
        b"; #@! TF.GenerationSoftware,Kicad," in data
        or b"; #@! TF.GenerationSoftware,KiCad," in data
        or b"; DRILL file KiCad " in data
    )
    if not is_kicad_gerber and not is_kicad_drill:
        return data

    normalized_lines: list[bytes] = []
    for line in data.splitlines(keepends=True):
        ending = _line_ending(line)
        body = line[: -len(ending)] if ending else line
        normalized_lines.append(
            _normalize_kicad_generated_line(
                body, is_kicad_gerber=is_kicad_gerber, is_kicad_drill=is_kicad_drill
            )
            + ending
        )
    return b"".join(normalized_lines)


def _normalized_snapshot_entries(root: Path) -> list[dict[str, str | int]]:
    entries: list[dict[str, str | int]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.name == _REFERENCE_MANIFEST_FILE:
            continue
        if path.is_symlink():
            raise ValueError("reference manufacturing snapshot must not contain symlinks")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        normalized = _normalize_kicad_timestamp_bytes(relative, path.read_bytes())
        entries.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(normalized).hexdigest(),
                "size_bytes": len(normalized),
            }
        )
    return entries


def _write_snapshot_manifest(
    root: Path, generation: ReferenceSnapshotGeneration
) -> dict[str, object]:
    entries = _snapshot_file_entries(root)
    payload: dict[str, object] = {
        "schema_version": "pcb-reference-manufacturing-snapshot.v1",
        "generation": generation,
        "artifact_manifest_digest": _manifest_digest(entries),
        "files": entries,
    }
    (root / _REFERENCE_MANIFEST_FILE).write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _require_snapshot_export_success(label: str, result: str) -> None:
    lowered = result.casefold()
    if "failed:" in lowered or "no files were produced" in lowered:
        raise ValueError(f"{label} export failed: {result}")


def _remove_same_file_bom_aliases(canonical: Path, candidates: list[Path]) -> None:
    for alias in candidates:
        if alias == canonical:
            continue
        if not alias.samefile(canonical):
            raise ValueError("reference manufacturing snapshot contains ambiguous BOM artifacts")
        alias.unlink()


def _rename_bom_case_safely(source: Path, canonical: Path) -> None:
    temporary = canonical.parent / ".reference-bom-case-normalize.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise ValueError(
            "reference manufacturing snapshot contains reserved temporary BOM artifact"
        )
    source.replace(temporary)
    try:
        temporary.replace(canonical)
    except OSError:
        if temporary.exists() and not source.exists():
            temporary.replace(source)
        raise


def _canonicalize_snapshot_bom(root: Path) -> Path:
    """Require one BOM artifact and normalize its on-disk spelling to ``BOM.csv``."""
    canonical_name = "BOM.csv"
    candidates = [
        path
        for path in root.iterdir()
        if path.name.casefold() == canonical_name.casefold() and path.is_file()
    ]
    canonical = root / canonical_name
    if not candidates:
        return canonical

    exact = next((path for path in candidates if path.name == canonical_name), None)
    if exact is not None:
        _remove_same_file_bom_aliases(exact, candidates)
        return exact

    if len(candidates) != 1:
        raise ValueError("reference manufacturing snapshot contains ambiguous BOM artifacts")
    _rename_bom_case_safely(candidates[0], canonical)
    return canonical


def generate_reference_manufacturing_snapshot(generation: ReferenceSnapshotGeneration) -> str:
    """Generate one fresh BOM + Gerber/drill snapshot with a stable byte manifest."""
    root = _reference_snapshot_root(generation)
    if root.is_symlink():
        raise ValueError("reference manufacturing snapshot root must not be a symlink")
    if root.exists() and any(root.iterdir()):
        raise ValueError("reference manufacturing snapshot already contains artifacts")
    root.mkdir(parents=True, exist_ok=True)
    services = _snapshot_export_services(root)
    _require_snapshot_export_success("Gerber", services.gerber.export("Gerbers"))
    _require_snapshot_export_success("Drill", services.drill.export("Gerbers"))
    _require_snapshot_export_success("BOM", services.bom.export("csv"))

    canonical_bom = _canonicalize_snapshot_bom(root)
    gerbers = root / "Gerbers"
    has_gerber = gerbers.is_dir() and any(
        path.is_file() and path.stat().st_size > 0 and path.suffix.casefold() != ".gbrjob"
        for path in gerbers.glob("*.g*")
    )
    has_drill = gerbers.is_dir() and any(
        path.is_file() and path.stat().st_size > 0
        for pattern in ("*.drl", "*.xnc")
        for path in gerbers.glob(pattern)
    )
    if (
        not canonical_bom.is_file()
        or canonical_bom.stat().st_size == 0
        or not has_gerber
        or not has_drill
    ):
        raise ValueError("reference manufacturing snapshot is missing BOM, Gerber, or drill output")
    return json.dumps(_write_snapshot_manifest(root, generation), sort_keys=True)


def _validated_snapshot_manifest(generation: ReferenceSnapshotGeneration) -> dict[str, object]:
    root = _reference_snapshot_root(generation)
    if root.is_symlink():
        raise ValueError("reference manufacturing snapshot root must not be a symlink")
    manifest_path = root / _REFERENCE_MANIFEST_FILE
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("reference manufacturing snapshot manifest is missing")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("reference manufacturing snapshot manifest is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("reference manufacturing snapshot manifest is invalid")
    actual_entries = _snapshot_file_entries(root)
    actual_digest = _manifest_digest(actual_entries)
    if (
        payload.get("schema_version") != "pcb-reference-manufacturing-snapshot.v1"
        or payload.get("generation") != generation
        or payload.get("files") != actual_entries
        or payload.get("artifact_manifest_digest") != actual_digest
    ):
        raise ValueError("reference manufacturing manifest no longer matches snapshot bytes")
    return payload


def compare_reference_manufacturing_snapshots() -> str:
    """Revalidate and compare two manufacturing generations without mutating artifacts."""
    first = _validated_snapshot_manifest("generation-1")
    second = _validated_snapshot_manifest("generation-2")
    first_root = _reference_snapshot_root("generation-1")
    second_root = _reference_snapshot_root("generation-2")
    first_normalized = _normalized_snapshot_entries(first_root)
    second_normalized = _normalized_snapshot_entries(second_root)
    normalized_digests = [
        _manifest_digest(first_normalized),
        _manifest_digest(second_normalized),
    ]

    if first["files"] == second["files"]:
        comparison = "byte_identical"
    elif first_normalized == second_normalized:
        comparison = "normalized_equivalent"
    else:
        comparison = "divergent"

    payload: dict[str, object] = {
        "schema_version": "pcb-reference-manufacturing-comparison.v1",
        "comparison": comparison,
        "artifact_manifest_digests": [
            first["artifact_manifest_digest"],
            second["artifact_manifest_digest"],
        ],
        "normalized_artifact_manifest_digests": normalized_digests,
    }
    if comparison == "normalized_equivalent":
        payload["normalization_rules_version"] = REFERENCE_MANUFACTURING_NORMALIZATION_RULES_VERSION
    parent = get_config().ensure_output_dir(_REFERENCE_SNAPSHOT_PARENT)
    (parent / _REFERENCE_COMPARISON_FILE).write_text(
        json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return json.dumps(payload, sort_keys=True)


def _register_reference_manufacturing_tools(server: KiCadFastMCP) -> None:
    @server.tool(name="reference_generate_manufacturing_snapshot")
    def reference_generate_manufacturing_snapshot(
        generation: ReferenceSnapshotGeneration,
    ) -> str:
        """Generate one of two fixed fresh manufacturing snapshots for benchmark evidence."""
        return generate_reference_manufacturing_snapshot(generation)

    @server.tool(name="reference_compare_manufacturing_snapshots")
    def reference_compare_manufacturing_snapshots() -> str:
        """Compare the two fixed manufacturing snapshot manifests after byte revalidation."""
        return compare_reference_manufacturing_snapshots()


def build_reference_manufacturing_server(*, defer_registration: bool = True) -> KiCadFastMCP:
    """Build a manufacturing-mode server narrowed to the reviewed benchmark surface."""
    server = cast(KiCadFastMCP, build_server("full", defer_registration=defer_registration))
    _register_reference_manufacturing_tools(server)
    exact = set(REFERENCE_MANUFACTURING_TOOL_NAMES)
    server.allowed_tool_names = exact
    server.execution_tool_names = exact
    return server


def main() -> None:
    """Run the benchmark-only reference manufacturing server over stdio."""
    with contextlib.redirect_stdout(sys.stderr):
        reset_config()
        cfg = get_config()
        if cfg.transport != "stdio":
            raise SystemExit("reference manufacturing benchmark server requires stdio transport")
        if cfg.operating_mode != "manufacturing":
            raise SystemExit("reference manufacturing benchmark server requires manufacturing mode")
        server = build_reference_manufacturing_server(defer_registration=True)
    _ensure_thread_aware_stdout()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
