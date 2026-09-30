"""Reviewed machine-readable tool effect contracts for external policy consumers.

This module is intentionally small and explicit. Presence in the normal capability
registry does not make a tool trusted for filesystem/effect authorization. Only
contracts listed here have had their argument/effect semantics source-reviewed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SCHEMA_VERSION = "1.0.0"
SOURCE_REPOSITORY = "oaslananka/kicad-mcp-pro"
REVIEWED_SOURCE_SHA = "e460e28a4dd0f2c105a1d2db3e26eb731769c543"

type OperationEffect = Literal["read", "write", "create", "delete"]
type TransactionSupport = Literal["none", "internal_guarded", "external_lifecycle", "unknown"]
type VerificationRequirement = Literal["source_review", "input_schema_match"]


@dataclass(frozen=True)
class PathArgumentEffect:
    argument: str
    effects: tuple[OperationEffect, ...]
    required: bool
    default: str | None = None
    base_argument: str | None = None


@dataclass(frozen=True)
class ReviewedToolEffect:
    name: str
    arguments: tuple[str, ...]
    effects: tuple[OperationEffect, ...]
    path_arguments: tuple[PathArgumentEffect, ...]
    destructive: bool
    idempotent: bool
    supports_dry_run: bool
    supports_rollback: bool
    transaction_support: TransactionSupport
    verification_requirements: tuple[VerificationRequirement, ...]
    reviewed_source_paths: tuple[str, ...]


REVIEWED_TOOL_EFFECTS: tuple[ReviewedToolEffect, ...] = (
    ReviewedToolEffect(
        name="sch_get_symbols",
        arguments=("sheet", "sheet_file"),
        effects=("read",),
        path_arguments=(
            PathArgumentEffect(
                argument="sheet_file",
                effects=("read",),
                required=False,
            ),
        ),
        destructive=False,
        idempotent=True,
        supports_dry_run=False,
        supports_rollback=False,
        transaction_support="none",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/schematic_inspection.py",),
    ),
    ReviewedToolEffect(
        name="pcb_auto_place_by_schematic",
        arguments=(
            "strategy",
            "origin_x_mm",
            "origin_y_mm",
            "scale_x",
            "scale_y",
            "grid_mm",
            "allow_open_board",
            "sync_missing",
        ),
        effects=("read", "write", "create"),
        path_arguments=(),
        destructive=True,
        idempotent=False,
        supports_dry_run=False,
        supports_rollback=False,
        transaction_support="none",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/pcb.py",),
    ),
    ReviewedToolEffect(
        name="kicad_create_new_project",
        arguments=("path", "name", "confirm_overwrite"),
        effects=(),
        path_arguments=(
            PathArgumentEffect(
                argument="path",
                effects=("read", "write", "create"),
                required=True,
            ),
            PathArgumentEffect(
                argument="name",
                effects=("read", "write", "create"),
                required=True,
                base_argument="path",
            ),
        ),
        destructive=True,
        idempotent=False,
        supports_dry_run=False,
        supports_rollback=False,
        transaction_support="none",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/project_creation.py",),
    ),
    ReviewedToolEffect(
        name="pcb_delete_items",
        arguments=("item_ids",),
        effects=("read", "delete"),
        path_arguments=(),
        destructive=True,
        idempotent=False,
        supports_dry_run=True,
        supports_rollback=False,
        transaction_support="internal_guarded",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/pcb.py",),
    ),
    ReviewedToolEffect(
        name="lib_create_custom_symbol",
        arguments=("name", "pins"),
        effects=("read", "write", "create"),
        path_arguments=(),
        destructive=True,
        idempotent=False,
        supports_dry_run=False,
        supports_rollback=False,
        transaction_support="none",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/library_local_authoring.py",),
    ),
    ReviewedToolEffect(
        name="export_gerber",
        arguments=("output_subdir", "layers"),
        effects=("read", "write"),
        path_arguments=(
            PathArgumentEffect(
                argument="output_subdir",
                effects=("create", "write"),
                required=False,
                default="gerber",
            ),
        ),
        destructive=True,
        idempotent=True,
        supports_dry_run=False,
        supports_rollback=False,
        transaction_support="none",
        verification_requirements=("source_review", "input_schema_match"),
        reviewed_source_paths=("src/kicad_mcp/tools/export_gerber.py",),
    ),
)


def reviewed_effects_by_name() -> dict[str, ReviewedToolEffect]:
    """Return reviewed effects keyed by tool name."""
    return {contract.name: contract for contract in REVIEWED_TOOL_EFFECTS}
