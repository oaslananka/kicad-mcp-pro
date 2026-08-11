"""Cross-platform export tools backed by kicad-cli."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess as _subprocess
import time as _time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context, FastMCP

from ..config import get_config
from ..discovery import get_cli_capabilities
from ..export.board_stats import ExportBoardStatsService
from ..export.bom import ExportBomService
from ..export.drill import ExportDrillService
from ..export.gerber import ExportGerberService
from ..export.netlist import ExportNetlistService
from ..export.pcb_3d_pdf import ExportPcb3dPdfService
from ..export.pcb_3d_render import ExportPcb3dRenderService
from ..export.pcb_file_formats import ExportPcbFileFormatsService
from ..export.pcb_manufacturing_outputs import ExportPcbManufacturingOutputsService
from ..export.pcb_pdf import ExportPcbPdfService
from ..export.pcb_vector import ExportPcbVectorService
from ..export.sch_pdf import ExportSchPdfService
from ..export.sch_python_bom import ExportSchPythonBomService
from ..export.sch_vector import ExportSchVectorService
from . import (
    export_board_stats,
    export_bom,
    export_drill,
    export_gerber,
    export_netlist,
    export_pcb_3d_pdf,
    export_pcb_3d_render,
    export_pcb_file_formats,
    export_pcb_manufacturing_outputs,
    export_pcb_pdf,
    export_pcb_vector,
    export_sch_pdf,
    export_sch_python_bom,
    export_sch_vector,
)
from .export_support import (
    _ensure_output_dir,
    _get_pcb_file,
    _get_sch_file,
    _run_cli,
    _run_cli_variants,
)
from .metadata import headless_compatible
from .variants import variant_apply_to_kicad_cli_args

# Public compatibility for tests and downstream monkeypatches.  These aliases
# point at Python's process/time modules, so monkeypatching
# kicad_mcp.tools.export.subprocess.run or .time.sleep still affects _run_cli's
# shared module objects.
subprocess = _subprocess
time = _time

DEFAULT_PCB_PDF_LAYERS = ["F.Cu", "Edge.Cuts"]
_WINDOWS_ANCHORED_PATH = re.compile(r"^(?:[a-zA-Z]:|//|\\\\)")
__all__ = [
    "_ensure_output_dir",
    "_get_pcb_file",
    "_get_sch_file",
    "_run_cli",
    "_run_cli_variants",
    "subprocess",
    "time",
]


def _safe_output_filename(raw_name: str, *, default_name: str) -> str:
    name = raw_name.strip() if raw_name else default_name
    if not name:
        raise ValueError("Output file names cannot be empty or whitespace only.")
    if "/" in name or "\\" in name:
        raise ValueError("Output file names cannot contain directory separators or traversal.")
    if _WINDOWS_ANCHORED_PATH.match(name):
        raise ValueError("Output file names must be relative to the export output directory.")
    candidate = Path(name).expanduser()
    if candidate.is_absolute() or candidate.anchor:
        raise ValueError("Output file names must be relative to the export output directory.")
    if len(candidate.parts) != 1 or candidate.name in {"", ".", ".."}:
        raise ValueError("Output file names cannot contain directory separators or traversal.")
    return candidate.name


def _resolve_output_file(subdir: str, raw_name: str, *, default_name: str) -> Path:
    return _ensure_output_dir(subdir) / _safe_output_filename(raw_name, default_name=default_name)


def _human_size(size_bytes: int) -> str:
    """Format a byte count as a human-readable string."""
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _format_file_list(files: list[Path], heading: str) -> str:
    if not files:
        return f"{heading}\nNo files were produced."
    lines = [heading]
    lines.extend(f"- {file.name}" for file in files[:25])
    if len(files) > 25:
        lines.append(f"... and {len(files) - 25} more files")
    return "\n".join(lines)


def _read_preview(path: Path) -> str:
    cfg = get_config()
    content = path.read_text(encoding="utf-8", errors="ignore")
    if len(content) > cfg.max_text_response_chars:
        return f"{content[: cfg.max_text_response_chars]}\n... [truncated]"
    return content


def _bom_project_schematic_files() -> list[Path]:
    from .schematic import project_schematic_files

    return project_schematic_files()


def _bom_schematic_component_rows() -> list[dict[str, str]]:
    from .library import _schematic_component_rows

    return _schematic_component_rows()


LOW_LEVEL_EXPORT_NOTICE = (
    "Debug export only: this low-level export does not enforce project_quality_gate(). "
    "Use export_manufacturing_package() for a gated release handoff."
)


def _with_low_level_export_notice(message: str) -> str:
    return f"{LOW_LEVEL_EXPORT_NOTICE}\n\n{message}"


def _release_evidence_error(path_text: str) -> str | None:
    if not path_text.strip():
        return (
            "Manufacturing package export is hard-blocked until approval_evidence_path is supplied."
        )
    try:
        path = get_config().resolve_within_project(path_text, allow_absolute=False)
    except ValueError as exc:
        return f"Manufacturing evidence path is invalid: {exc}"
    if not path.exists() or not path.is_file():
        return f"Manufacturing evidence file does not exist: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"Manufacturing evidence must be readable JSON: {exc}"
    if not isinstance(payload, dict):
        return "Manufacturing evidence must be a JSON object."
    missing = [
        key
        for key in ("approved_by", "approved_at_utc", "approval_scope")
        if not str(payload.get(key) or "").strip()
    ]
    if missing:
        return "Manufacturing evidence is missing: " + ", ".join(missing)
    return None


def _load_release_evidence(path_text: str) -> tuple[Path, dict[str, Any]]:
    path = get_config().resolve_within_project(path_text, allow_absolute=False)
    return path, dict(json.loads(path.read_text(encoding="utf-8")))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manufacturing_artifacts() -> list[dict[str, Any]]:
    root = _ensure_output_dir()
    files: list[Path] = []
    for subdir in (root, root / "gerber", root / "pos", root / "ipc2581", root / "odb"):
        if subdir.exists():
            files.extend(path for path in subdir.rglob("*") if path.is_file())
    records = []
    for path in sorted(set(files)):
        relative = str(path.relative_to(root)) if path.is_relative_to(root) else path.name
        records.append(
            {
                "path": str(path),
                "relative_path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _file_sha256(path),
            }
        )
    return records


def _write_handoff_report(
    *,
    variant_name: str | None,
    evidence_path: Path,
    evidence: dict[str, Any],
    outcomes: list[Any],
    results: list[str],
) -> Path:
    out_dir = _ensure_output_dir()
    report_path = out_dir / "manufacturing_release_report.json"
    payload = {
        "schema_version": "manufacturing_release.v1",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "variant": variant_name or "default",
        "approval_evidence_path": str(evidence_path),
        "approval_evidence": evidence,
        "quality_gate": [
            {
                "name": item.name,
                "status": item.status,
                "summary": item.summary,
                "details": item.details,
            }
            for item in outcomes
        ],
        "export_results": results,
        "artifacts": _manufacturing_artifacts(),
    }
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return report_path


def _active_variant_args(variant_name: str | None = None) -> list[str]:
    try:
        args = variant_apply_to_kicad_cli_args(variant_name)
    except ValueError:
        if variant_name:
            raise
        return []
    if not args:
        return args
    # ``--variant`` was added to ``kicad-cli`` in KiCad 10.  Earlier CLIs (9.x
    # and below) reject it as ``Unknown argument`` and abort the export.  The
    # ``default`` variant is a synthetic no-op baseline that adds no overrides,
    # so suppress it unconditionally; for explicit non-default variants, gate
    # on the local CLI's advertised capability.
    if args == ["--variant", "default"]:
        return []
    try:
        caps = get_cli_capabilities(get_config().kicad_cli)
    except Exception:
        return args
    if not caps.supports_cli_variant:
        raise ValueError(
            f"The detected kicad-cli does not support --variant. "
            f"Cannot apply variant '{args[1]}'. Upgrade to KiCad 10+ "
            f"or run variant_set_active('default') to clear the override."
        )
    return args


async def _report_progress(
    ctx: Context[Any, Any, Any] | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except ValueError:
        return


def register(mcp: FastMCP, *, include_low_level_exports: bool = True) -> None:
    """Register export tools."""
    gerber_service = ExportGerberService(
        get_pcb_file=_get_pcb_file,
        ensure_output_dir=_ensure_output_dir,
        get_gerber_command=lambda: get_cli_capabilities(get_config().kicad_cli).gerber_command,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )

    bom_service = ExportBomService(
        get_sch_file=_get_sch_file,
        ensure_output_dir=lambda: _ensure_output_dir(),
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        read_preview=_read_preview,
        project_schematic_files=_bom_project_schematic_files,
        schematic_component_rows=_bom_schematic_component_rows,
    )

    drill_service = ExportDrillService(
        get_pcb_file=_get_pcb_file,
        ensure_output_dir=_ensure_output_dir,
        get_drill_command=lambda: get_cli_capabilities(get_config().kicad_cli).drill_command,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )

    pcb_3d_pdf_service = ExportPcb3dPdfService(
        get_pcb_file=_get_pcb_file,
        supports_3d_pdf=lambda: get_cli_capabilities(get_config().kicad_cli).supports_3d_pdf,
        resolve_output_file=lambda output_path: _resolve_output_file(
            "pdf", output_path, default_name="board-3d.pdf"
        ),
        active_variant_args=lambda: _active_variant_args(),
        run_cli_variants=_run_cli_variants,
    )

    pcb_3d_render_service = ExportPcb3dRenderService(
        get_pcb_file=_get_pcb_file,
        is_supported=lambda: get_cli_capabilities(get_config().kicad_cli).supports_render,
        resolve_output_file=_resolve_output_file,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        human_size=_human_size,
    )

    pcb_pdf_service = ExportPcbPdfService(
        get_pcb_file=_get_pcb_file,
        ensure_output_dir=_ensure_output_dir,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        default_layers=DEFAULT_PCB_PDF_LAYERS,
    )

    pcb_file_formats_service = ExportPcbFileFormatsService(
        get_pcb_file=_get_pcb_file,
        is_supported=lambda format_name: bool(
            getattr(
                get_cli_capabilities(get_config().kicad_cli),
                "supports_ipc_d356" if format_name == "ipc_d356" else f"supports_{format_name}",
            )
        ),
        resolve_output_file=_resolve_output_file,
        active_variant_args=_active_variant_args,
        run_cli=_run_cli,
    )

    pcb_manufacturing_outputs_service = ExportPcbManufacturingOutputsService(
        get_pcb_file=_get_pcb_file,
        get_capabilities=lambda: get_cli_capabilities(get_config().kicad_cli),
        ensure_output_dir=_ensure_output_dir,
        resolve_output_file=_resolve_output_file,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )

    pcb_vector_service = ExportPcbVectorService(
        get_pcb_file=_get_pcb_file,
        get_capabilities=lambda: get_cli_capabilities(get_config().kicad_cli),
        ensure_output_dir=_ensure_output_dir,
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
        format_file_list=_format_file_list,
    )

    sch_pdf_service = ExportSchPdfService(
        get_sch_file=_get_sch_file,
        ensure_output_dir=lambda: _ensure_output_dir(),
        active_variant_args=_active_variant_args,
        run_cli_variants=_run_cli_variants,
    )

    sch_python_bom_service = ExportSchPythonBomService(
        get_sch_file=_get_sch_file,
        resolve_output_file=_resolve_output_file,
        run_cli=_run_cli,
    )

    sch_vector_service = ExportSchVectorService(
        get_sch_file=_get_sch_file,
        ensure_output_dir=_ensure_output_dir,
        resolve_output_file=_resolve_output_file,
        run_cli=_run_cli,
        format_file_list=_format_file_list,
    )

    @headless_compatible
    async def export_manufacturing_package(
        variant: str = "",
        approval_evidence_path: str = "",
        ctx: Context[Any, Any, Any] | None = None,
    ) -> str:
        """Generate the gated manufacturing release package."""
        import anyio

        from .validation import _evaluate_project_gate, _render_project_gate_report

        variant_name = variant.strip() or None
        await _report_progress(ctx, 5, 100, "Running full project quality gate...")
        outcomes = await anyio.to_thread.run_sync(_evaluate_project_gate)
        blocking = [outcome for outcome in outcomes if outcome.status != "PASS"]
        if blocking:
            return _render_project_gate_report(
                blocking,
                summary=(
                    "- Manufacturing package export is hard-blocked until the full "
                    "project quality gate passes."
                ),
            )

        evidence_error = _release_evidence_error(approval_evidence_path)
        if evidence_error is not None:
            return "\n".join(
                [
                    evidence_error,
                    "- Run project_signoff_report() before final release export.",
                    "- Store reviewer approval in a project-local JSON evidence file.",
                ]
            )
        evidence_path, evidence_payload = _load_release_evidence(approval_evidence_path)

        await _report_progress(ctx, 25, 100, "Exporting Gerbers...")
        results = [
            await anyio.to_thread.run_sync(
                lambda: gerber_service.export(variant_name=variant_name)
            ),
        ]
        await _report_progress(ctx, 45, 100, "Exporting drill files...")
        results.extend(
            [
                await anyio.to_thread.run_sync(
                    lambda: drill_service.export(variant_name=variant_name)
                )
            ]
        )
        await _report_progress(ctx, 65, 100, "Exporting BOM...")
        results.extend(
            [
                await anyio.to_thread.run_sync(
                    lambda: bom_service.export(variant_name=variant_name)
                ),
            ]
        )
        await _report_progress(ctx, 85, 100, "Exporting pick-and-place data...")
        results.extend(
            [
                await anyio.to_thread.run_sync(
                    lambda: pcb_manufacturing_outputs_service.export_pick_and_place(
                        variant_name=variant_name
                    )
                ),
            ]
        )
        ipc_result = await anyio.to_thread.run_sync(
            lambda: pcb_manufacturing_outputs_service.export_ipc2581(variant_name=variant_name)
        )
        if not ipc_result.startswith("IPC-2581 export is not supported"):
            results.append(ipc_result)
        odb_result = await anyio.to_thread.run_sync(
            lambda: pcb_manufacturing_outputs_service.export_odb(variant_name=variant_name)
        )
        if not odb_result.startswith("ODB++ export is not supported"):
            results.append(odb_result)
        report_path = _write_handoff_report(
            variant_name=variant_name,
            evidence_path=evidence_path,
            evidence=evidence_payload,
            outcomes=outcomes,
            results=results,
        )
        artifact_count = len(_manufacturing_artifacts())
        results.append(
            "\n".join(
                [
                    "Manufacturing release evidence:",
                    f"- Approval evidence: {evidence_path}",
                    f"- Release report: {report_path}",
                    f"- Linked artifacts: {artifact_count}",
                    "- Human approval is recorded as evidence, not replaced by automation.",
                ]
            )
        )
        await _report_progress(ctx, 100, 100, "Manufacturing package complete.")
        return "\n\n".join(results)

    if include_low_level_exports:
        export_gerber.register(
            mcp,
            export_gerber.ExportGerberDependencies(
                service=gerber_service,
                add_low_level_notice=_with_low_level_export_notice,
                report_progress=_report_progress,
            ),
        )
        export_drill.register(
            mcp,
            export_drill.ExportDrillDependencies(
                service=drill_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_bom.register(
            mcp,
            export_bom.ExportBomDependencies(
                service=bom_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_netlist.register(
            mcp,
            export_netlist.ExportNetlistDependencies(
                service=ExportNetlistService(
                    get_sch_file=_get_sch_file,
                    ensure_output_dir=_ensure_output_dir,
                    active_variant_args=_active_variant_args,
                    run_cli_variants=_run_cli_variants,
                ),
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_pdf.register(
            mcp,
            export_pcb_pdf.ExportPcbPdfDependencies(
                service=pcb_pdf_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_sch_pdf.register(
            mcp,
            export_sch_pdf.ExportSchPdfDependencies(
                service=sch_pdf_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_sch_vector.register(
            mcp,
            export_sch_vector.ExportSchVectorDependencies(
                service=sch_vector_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_sch_python_bom.register(
            mcp,
            export_sch_python_bom.ExportSchPythonBomDependencies(
                service=sch_python_bom_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_file_formats.register(
            mcp,
            export_pcb_file_formats.ExportPcbFileFormatsDependencies(
                service=pcb_file_formats_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_3d_pdf.register(
            mcp,
            export_pcb_3d_pdf.ExportPcb3dPdfDependencies(
                service=pcb_3d_pdf_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_3d_render.register(
            mcp,
            export_pcb_3d_render.ExportPcb3dRenderDependencies(
                service=pcb_3d_render_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_manufacturing_outputs.register(
            mcp,
            export_pcb_manufacturing_outputs.ExportPcbManufacturingOutputsDependencies(
                service=pcb_manufacturing_outputs_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )
        export_pcb_vector.register(
            mcp,
            export_pcb_vector.ExportPcbVectorDependencies(
                service=pcb_vector_service,
                add_low_level_notice=_with_low_level_export_notice,
            ),
        )

    board_stats_dependencies = export_board_stats.ExportBoardStatsDependencies(
        service=ExportBoardStatsService(
            get_pcb_file=_get_pcb_file,
            ensure_output_dir=_ensure_output_dir,
            run_cli_variants=_run_cli_variants,
            read_preview=_read_preview,
        )
    )
    export_board_stats.register(
        mcp,
        board_stats_dependencies,
        include_json=False,
    )
    mcp.tool()(export_manufacturing_package)
    export_board_stats.register(
        mcp,
        board_stats_dependencies,
        include_preview=False,
    )
