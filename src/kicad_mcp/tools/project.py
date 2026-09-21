"""Project setup and discovery tools."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import structlog
from mcp.server.fastmcp import FastMCP

from .. import __version__
from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad, reset_connection
from ..discovery import (
    discover_library_paths,
    find_kicad_version,
    find_recent_projects,
    scan_project_dir,
)
from ..file_formats import upgrade_generated_file
from ..ipc.runtime_probe import probe_project_runtime
from ..operating_modes import OperatingMode, active_operating_mode
from ..path_safety import assert_within
from ..pcb.live_edit_runtime import reset_live_edit_service
from ..project.context import ProjectContextService
from ..project.creation import ProjectCreationService
from ..project.design_spec import (
    ProjectDesignSpecService,
    ProjectImportDesignSpecPayload,
    ProjectSpecPayload,
    ProjectSpecValidationPayload,
    _infer_design_intent_from_board,
    _render_design_intent,
    _render_project_spec_resolution,
    import_design_spec,
    load_design_intent,
    resolve_design_intent,
    save_design_intent,
    validate_design_intent,
)
from ..project.design_spec import (
    _normalize_design_intent as _normalize_design_intent,
)
from ..project.design_spec import (
    _persist_project_spec as _persist_project_spec,
)
from ..project.discovery import ProjectDiscoveryService
from ..project.edit_impact import ProjectEditImpactService
from ..project.help import ProjectHelpService
from ..project.next_action import GateOutcomeLike, ProjectNextActionService
from ..project.reporting import (
    DesignReportPayload as DesignReportPayload,
)
from ..project.reporting import (
    FixerActionLike,
    GateHistoryLike,
    ProjectDesignIntentLike,
    ProjectReportingService,
    ProjectSpecResolutionLike,
)
from ..project.runtime import ProjectRuntimeService
from ..project.validation_loops import (
    AutoFixAction as AutoFixAction,
)
from ..project.validation_loops import (
    AutoFixLoopPayload as AutoFixLoopPayload,
)
from ..project.validation_loops import (
    ProjectValidationLoopService,
)
from ..project.workflow import ProjectWorkflowService
from ..utils.cache import clear_ttl_cache
from . import (
    project_context,
    project_creation,
    project_design_spec,
    project_discovery,
    project_edit_impact,
    project_edit_revalidation,
    project_help,
    project_next_action,
    project_reporting,
    project_runtime,
    project_validation_loops,
    project_workflow,
)
from .design_intent_state import (
    DecouplingPairIntent,
    ProjectDesignIntent,
    ProjectDesignSpec,
    ProjectSpecResolution,
    ProjectSpecSource,
    RFKeepoutIntent,
)
from .export_support import _run_cli
from .fixers import fixers_for_gate, sampling_prompt_for_gate
from .router import TOOL_CATEGORIES, available_profiles

_HELP_CATEGORY_DESCRIPTIONS: dict[str, str] = {
    category: info["description"] for category, info in TOOL_CATEGORIES.items()
}

logger = structlog.get_logger(__name__)
__all__ = [
    "DecouplingPairIntent",
    "ProjectDesignIntent",
    "ProjectDesignSpec",
    "ProjectSpecResolution",
    "ProjectSpecSource",
    "RFKeepoutIntent",
    "resolve_design_intent",
    "load_design_intent",
    "save_design_intent",
    "import_design_spec",
    "validate_design_intent",
    "_render_project_spec_resolution",
    "ProjectSpecPayload",
    "ProjectImportDesignSpecPayload",
    "ProjectSpecValidationPayload",
]


def _render_project_info() -> str:
    cfg = get_config()
    cli_status = "found" if cfg.kicad_cli.exists() else "missing"
    operating_mode = active_operating_mode(cfg)
    experimental_enabled = operating_mode is OperatingMode.EXPERIMENTAL
    return "\n".join(
        [
            "Current project configuration:",
            f"- Project directory: {cfg.project_dir or '(not set)'}",
            f"- Project file: {cfg.project_file or '(not set)'}",
            f"- Resolved project: {cfg.project_file or '(not set)'}",
            f"- PCB file: {cfg.pcb_file or '(not set)'}",
            f"- Schematic file: {cfg.sch_file or '(not set)'}",
            f"- Output directory: {cfg.output_dir or '(not set)'}",
            f"- KiCad CLI: {cfg.kicad_cli} ({cli_status})",
            f"- Server profile: {cfg.profile}",
            f"- Experimental tools: {experimental_enabled}",
        ]
    )


def _new_project_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
    project_file = project_dir / f"{name}.kicad_pro"
    pcb_file = project_dir / f"{name}.kicad_pcb"
    sch_file = project_dir / f"{name}.kicad_sch"
    return project_file, pcb_file, sch_file


def _minimal_project_payload(project_file: Path) -> dict[str, Any]:
    return {
        "board": {"design_settings": {}},
        "meta": {"filename": project_file.name, "version": 1},
        "schematic": {"legacy_lib_dir": "", "page_layout_descr_file": ""},
    }


def _new_project_payload(kicad_cli: Path, project_file: Path) -> dict[str, Any]:
    share_root = discover_library_paths(kicad_cli).get("root")
    if share_root is not None:
        template_file = share_root / "template" / "kicad.kicad_pro"
        if template_file.is_file():
            try:
                payload = json.loads(template_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "kicad_project_template_read_failed",
                    template=str(template_file),
                    error=str(exc),
                )
            else:
                if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
                    payload["meta"]["filename"] = project_file.name
                    return cast(dict[str, Any], payload)
                logger.warning(
                    "kicad_project_template_invalid",
                    template=str(template_file),
                )
    return _minimal_project_payload(project_file)


def _evaluate_project_gate_for_next_action() -> Sequence[GateOutcomeLike]:
    from .validation import _evaluate_project_gate

    return _evaluate_project_gate()


def _evaluate_project_gate_for_validation_loops() -> Sequence[GateOutcomeLike]:
    from .validation import _evaluate_project_gate

    return _evaluate_project_gate()


def _sampling_prompt_for_validation_loops(
    gate_name: str,
    summary: str,
    details: list[str] | None = None,
) -> str:
    return sampling_prompt_for_gate(gate_name, summary, details)


def _history_for_active_project_for_reporting() -> GateHistoryLike:
    from ..resources.gate_history import GateHistory

    return GateHistory.for_active_project()


def _resolve_design_intent_for_reporting() -> ProjectSpecResolutionLike:
    return cast(ProjectSpecResolutionLike, resolve_design_intent())


def _render_design_intent_for_reporting(intent: ProjectDesignIntentLike) -> str:
    return _render_design_intent(cast(ProjectDesignIntent, intent))


def _evaluate_project_gate_for_reporting() -> Sequence[GateOutcomeLike]:
    from .validation import _evaluate_project_gate

    return _evaluate_project_gate()


def _fixers_for_gate_for_reporting(gate_name: str) -> Sequence[FixerActionLike]:
    return cast(Sequence[FixerActionLike], fixers_for_gate(gate_name))


def register(mcp: FastMCP) -> None:
    """Register project management tools."""

    context_service = ProjectContextService(
        scan_project_dir=scan_project_dir,
        apply_project=lambda project_dir, **kwargs: get_config().apply_project(
            project_dir, **kwargs
        ),
        clear_cache=clear_ttl_cache,
        reset_connection=reset_connection,
        reset_live_edit=reset_live_edit_service,
        render_project_info=_render_project_info,
    )
    project_context.register(
        mcp,
        project_context.ProjectContextDependencies(service=context_service),
    )

    workflow_service = ProjectWorkflowService()
    project_workflow.register(
        mcp,
        project_workflow.ProjectWorkflowDependencies(service=workflow_service),
    )

    next_action_service = ProjectNextActionService(
        evaluate_project_gate=_evaluate_project_gate_for_next_action
    )
    design_spec_service = ProjectDesignSpecService()
    project_design_spec.register(
        mcp,
        project_design_spec.ProjectDesignSpecDependencies(service=design_spec_service),
    )

    from .gates import _combined_status
    from .validation import PROJECT_GATE_CATEGORIES, _evaluate_project_gate, _format_gate

    edit_impact_service = ProjectEditImpactService(
        load_baseline=lambda: load_design_intent().model_dump(),
        infer_current=lambda: _infer_design_intent_from_board()[0].model_dump(),
        evaluate_project_gate=_evaluate_project_gate,
        combined_status=_combined_status,
        format_gate=_format_gate,
        project_gate_categories=PROJECT_GATE_CATEGORIES,
        inference_error_types=(KiCadConnectionError,),
    )
    project_edit_impact.register(
        mcp,
        project_edit_impact.ProjectEditImpactDependencies(service=edit_impact_service),
    )
    project_edit_revalidation.register(
        mcp,
        project_edit_revalidation.ProjectEditRevalidationDependencies(service=edit_impact_service),
    )

    project_next_action.register(
        mcp,
        project_next_action.ProjectNextActionDependencies(service=next_action_service),
    )

    validation_loop_service = ProjectValidationLoopService(
        evaluate_project_gate=_evaluate_project_gate_for_validation_loops,
        fixers_for_gate=lambda gate_name: fixers_for_gate(gate_name),
        resolve_callable=project_validation_loops.resolve_fixer_callable,
    )
    project_validation_loops.register(
        mcp,
        project_validation_loops.ProjectValidationLoopDependencies(
            service=validation_loop_service,
            sampling_prompt_for_gate=_sampling_prompt_for_validation_loops,
        ),
    )

    reporting_service = ProjectReportingService(
        history_for_active_project=_history_for_active_project_for_reporting,
        resolve_design_intent=_resolve_design_intent_for_reporting,
        render_design_intent=_render_design_intent_for_reporting,
        evaluate_project_gate=_evaluate_project_gate_for_reporting,
        fixers_for_gate=_fixers_for_gate_for_reporting,
    )
    project_reporting.register(
        mcp,
        project_reporting.ProjectReportingDependencies(service=reporting_service),
    )

    discovery_service = ProjectDiscoveryService(
        find_recent_projects=find_recent_projects,
        scan_project_dir=scan_project_dir,
    )
    project_discovery.register(
        mcp,
        project_discovery.ProjectDiscoveryDependencies(service=discovery_service),
    )

    creation_service = ProjectCreationService(
        get_config=lambda: get_config(),
        assert_within=lambda root, candidate: assert_within(root, candidate),
        new_project_files=lambda project_dir, name: _new_project_files(project_dir, name),
        new_project_payload=lambda kicad_cli, project_file: _new_project_payload(
            kicad_cli, project_file
        ),
        upgrade_file=lambda path, kind, allowed_root: upgrade_generated_file(
            path, kind, _run_cli, allowed_root=allowed_root
        ),
        reset_connection=lambda: reset_connection(),
        reset_live_edit=reset_live_edit_service,
    )
    project_creation.register(
        mcp,
        project_creation.ProjectCreationDependencies(service=creation_service),
    )

    runtime_service = ProjectRuntimeService(
        server_version=__version__,
        get_config=lambda: get_config(),
        find_kicad_version=lambda path: find_kicad_version(path),
        probe_ipc=lambda: probe_project_runtime(client_factory=get_kicad),
    )
    project_runtime.register(
        mcp,
        project_runtime.ProjectRuntimeDependencies(service=runtime_service),
    )

    help_service = ProjectHelpService(
        category_descriptions=lambda: _HELP_CATEGORY_DESCRIPTIONS,
        available_profiles=available_profiles,
    )
    project_help.register(
        mcp,
        project_help.ProjectHelpDependencies(service=help_service),
    )
