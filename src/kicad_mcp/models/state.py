"""Typed world-state models for KiCad MCP Pro.

These models are the single representation of project state used by:

- Tool pre/post condition checks
- Journal entries
- Rollback tokens
- Planner / verifier layers
- Telemetry events
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class WorkspaceState(BaseModel):
    """Represents the MCP server workspace context."""

    model_config = ConfigDict(frozen=True)

    project_dir: str | None = None
    workspace_root: str | None = None
    profile: str = "minimal"
    kicad_version_detected: str | None = None
    ipc_available: bool = False
    cli_available: bool = False
    timestamp: datetime = Field(default_factory=_utc_now)


class SchematicState(BaseModel):
    """Immutable snapshot of a schematic's observable state."""

    model_config = ConfigDict(frozen=True)

    sch_path: str
    sheet_count: int = 0
    symbol_count: int = 0
    net_count: int = 0
    label_count: int = 0
    has_hierarchy: bool = False
    erc_error_count: int | None = None
    content_hash: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> SchematicState:
        """Create a snapshot from a file path. Hashes file content."""
        content_hash = None
        if path.exists():
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(sch_path=str(path), content_hash=content_hash)


class BoardState(BaseModel):
    """Immutable snapshot of a PCB board's observable state."""

    model_config = ConfigDict(frozen=True)

    pcb_path: str
    footprint_count: int = 0
    track_count: int = 0
    via_count: int = 0
    layer_count: int = 0
    unrouted_count: int | None = None
    drc_error_count: int | None = None
    content_hash: str | None = None

    @classmethod
    def from_path(cls, path: Path) -> BoardState:
        """Create a snapshot from a file path. Hashes file content."""
        content_hash = None
        if path.exists():
            content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        return cls(pcb_path=str(path), content_hash=content_hash)


class ManufacturingState(BaseModel):
    """State of manufacturing output files."""

    model_config = ConfigDict(frozen=True)

    output_dir: str | None = None
    gerber_count: int = 0
    drill_files: list[str] = Field(default_factory=list)
    bom_path: str | None = None
    netlist_path: str | None = None
    step_path: str | None = None
    bundle_hash: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None


class VerificationState(BaseModel):
    """Aggregated quality gate results."""

    model_config = ConfigDict(frozen=True)

    gate_passed: bool = False
    erc_errors: int = 0
    drc_errors: int = 0
    dfm_violations: int = 0
    connectivity_ok: bool | None = None
    bom_complete: bool | None = None
    run_at: datetime = Field(default_factory=_utc_now)
    gate_id: str = Field(default_factory=lambda: str(uuid4()))


class CapabilityState(BaseModel):
    """Runtime capability detection result."""

    model_config = ConfigDict(frozen=True)

    kicad_cli_path: str | None = None
    kicad_cli_version: str | None = None
    ipc_reachable: bool = False
    ngspice_available: bool = False
    freerouting_available: bool = False
    profile: str = "minimal"
    available_tools: list[str] = Field(default_factory=list)


class AgentRunState(BaseModel):
    """Mutable runtime state for a single agent task execution."""

    model_config = ConfigDict(frozen=False)

    run_id: str = Field(default_factory=lambda: str(uuid4()))
    started_at: datetime = Field(default_factory=_utc_now)
    tool_calls: list[str] = Field(default_factory=list)
    journal_entries: list[str] = Field(default_factory=list)
    current_phase: str = "init"
    error_count: int = 0
    warning_count: int = 0

    def record_tool_call(self, tool_name: str) -> None:
        """Record a tool invocation in this run."""
        self.tool_calls.append(tool_name)

    def to_summary(self) -> dict[str, object]:
        """Return a compact JSON-serializable run summary."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "tool_calls_count": len(self.tool_calls),
            "journal_entries_count": len(self.journal_entries),
            "current_phase": self.current_phase,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


class ProjectState(BaseModel):
    """Composite project state snapshot."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace: WorkspaceState = Field(default_factory=WorkspaceState)
    schematic: SchematicState | None = None
    board: BoardState | None = None
    verification: VerificationState | None = None
    manufacturing: ManufacturingState | None = None

    def content_fingerprint(self) -> str:
        """Return a deterministic fingerprint of the mutable file state."""
        parts = []
        if self.schematic and self.schematic.content_hash:
            parts.append(self.schematic.content_hash)
        if self.board and self.board.content_hash:
            parts.append(self.board.content_hash)
        combined = "|".join(sorted(parts))
        return hashlib.sha256(combined.encode()).hexdigest()
