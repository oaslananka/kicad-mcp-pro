"""Tool metadata decorators used for discovery and profile documentation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from mcp.types import ToolAnnotations


@dataclass(frozen=True)
class ToolMetadata:
    """Discovery metadata attached to a public MCP tool."""

    headless_compatible: bool = False
    requires_kicad_running: bool = False
    dependencies: tuple[str, ...] = ()


_TOOL_METADATA: dict[str, ToolMetadata] = {}
_READ_ONLY_PREFIXES = (
    "get_",
    "list_",
    "search_",
    "trace_",
    "check_",
    "validate_",
    "score_",
    "run_drc",
    "run_erc",
    "kicad_get_",
    "kicad_help",
    "kicad_list_",
    "kicad_scan_",
    "project_get_",
    "drc_list_",
    "lib_get_",
    "lib_list_",
    "lib_recommend_",
    "lib_check_",
    "lib_find_",
    "mfg_check_",
)
_WRITE_PREFIXES = (
    "add_",
    "set_",
    "update_",
    "delete_",
    "move_",
    "create_",
    "place_",
    "apply_",
    "import_",
    "export_",
    "sync_",
    "begin_",
    "push_",
    "drop_",
)


def _merge_metadata(
    current: ToolMetadata,
    *,
    headless_compatible: bool | None = None,
    requires_kicad_running: bool | None = None,
    dependency: str | None = None,
) -> ToolMetadata:
    dependencies = list(current.dependencies)
    if dependency and dependency not in dependencies:
        dependencies.append(dependency)
    return ToolMetadata(
        headless_compatible=(
            current.headless_compatible
            if headless_compatible is None
            else current.headless_compatible or headless_compatible
        ),
        requires_kicad_running=(
            current.requires_kicad_running
            if requires_kicad_running is None
            else current.requires_kicad_running or requires_kicad_running
        ),
        dependencies=tuple(dependencies),
    )


def _apply_metadata[**P, R](
    func: Callable[P, R],
    *,
    headless_compatible: bool | None = None,
    requires_kicad_running: bool | None = None,
    dependency: str | None = None,
) -> Callable[P, R]:
    current = _TOOL_METADATA.get(func.__name__, ToolMetadata())
    updated = _merge_metadata(
        current,
        headless_compatible=headless_compatible,
        requires_kicad_running=requires_kicad_running,
        dependency=dependency,
    )
    _TOOL_METADATA[func.__name__] = updated
    return func


def headless_compatible[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Mark a tool as usable without a live KiCad IPC session."""
    return _apply_metadata(func, headless_compatible=True)


def requires_kicad_running[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Mark a tool as requiring an active KiCad IPC connection."""
    return _apply_metadata(func, requires_kicad_running=True)


def requires_dependency(name: str) -> Callable[[Callable[..., object]], Callable[..., object]]:
    """Mark a tool as requiring an optional dependency family."""

    def decorator[**P, R](func: Callable[P, R]) -> Callable[P, R]:
        return _apply_metadata(func, dependency=name)

    return decorator


def get_tool_metadata(tool_name: str) -> ToolMetadata | None:
    """Return discovery metadata for a registered tool name."""
    return _TOOL_METADATA.get(tool_name)


# Converging write verbs whose repetition lands on the same state. Additive or
# sequence-sensitive writes (add/create/place/route/build/commit) are deliberately
# excluded, so they are classified non-idempotent.
_IDEMPOTENT_WRITE_TOKENS = ("set_", "save", "refill", "export", "upgrade", "reset_")
_IDEMPOTENT_TOOL_NAMES = {"sch_spread_sheets", "sch_wire_sheet_pins"}


def _is_read_only_name(normalized: str) -> bool:
    return (
        normalized.startswith(_READ_ONLY_PREFIXES)
        or normalized.startswith("lib_search_")
        or normalized.startswith("pcb_get_")
        or normalized.startswith("sch_get_")
        or normalized.startswith("si_get_")
        or normalized.endswith("_quality_gate")
    )


def is_tool_idempotent(tool_name: str) -> bool:
    """Return whether re-invoking the tool with the same args is safe (no double-apply).

    Read-only tools are always idempotent. Among writes, only converging operations
    (set/save/refill/export/upgrade/reset) are idempotent; additive or sequence-sensitive
    writes are not, so an agent must reconcile state before retrying them on a transient
    error rather than blindly re-calling.
    """
    normalized = tool_name.casefold()
    if _is_read_only_name(normalized) or normalized in _IDEMPOTENT_TOOL_NAMES:
        return True
    return any(token in normalized for token in _IDEMPOTENT_WRITE_TOKENS)


def infer_tool_annotations(
    tool_name: str,
    explicit: ToolAnnotations | dict[str, object] | None = None,
) -> ToolAnnotations:
    """Infer MCP 2026-style annotations from existing tool metadata and naming."""
    metadata = get_tool_metadata(tool_name) or ToolMetadata()
    normalized = tool_name.casefold()

    is_read_only = _is_read_only_name(normalized)

    is_write = (
        normalized.startswith(_WRITE_PREFIXES)
        or any(
            token in normalized
            for token in (
                "_add_",
                "_delete_",
                "_modify_",
                "_move_",
                "_place_",
                "_route_",
                "_spread_",
                "_wire_",
                "_set_",
                "_update_",
                "_export_",
                "_import_",
            )
        )
        or any(
            token in normalized
            for token in (
                "annotate",
                "autofix",
                "auto_fix",
                "autoroute",
                "panelize",
                "restore_checkpoint",
                "commit_checkpoint",
                "revert",
            )
        )
    ) and not is_read_only

    annotations: dict[str, object] = {}
    if is_read_only:
        annotations["readOnlyHint"] = True
    # Set idempotency explicitly for every tool so agents can decide retry safety.
    annotations["idempotentHint"] = is_tool_idempotent(tool_name)
    if is_write:
        annotations["destructiveHint"] = True
    if metadata.requires_kicad_running:
        annotations["requiresKiCadRunning"] = True
    if any(
        token in normalized
        for token in (
            "export",
            "generate_release_manifest",
            "panelize",
            "render",
            "import_",
        )
    ):
        annotations["openWorldHint"] = True
    if explicit:
        explicit_values = (
            explicit.model_dump(exclude_none=True)
            if isinstance(explicit, ToolAnnotations)
            else dict(explicit)
        )
        annotations.update(explicit_values)
    return ToolAnnotations.model_validate(annotations)
