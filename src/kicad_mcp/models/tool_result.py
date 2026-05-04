"""Normalized result envelope for KiCad MCP Pro tools.

Every tool that mutates state, writes files, or performs external operations should return
or be wrapped to return a :class:`ToolResult`.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class ArtifactRef(BaseModel):
    """Reference to a produced output file."""

    model_config = ConfigDict(frozen=True)

    path: str
    kind: str
    size_bytes: int | None = None
    sha256: str | None = None


class StateDelta(BaseModel):
    """Describes the state change produced by a tool call."""

    model_config = ConfigDict(frozen=True)

    pre_fingerprint: str | None = None
    post_fingerprint: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    summary: str = ""


class ToolResult(BaseModel):
    """Normalized result returned by mutating KiCad MCP Pro tools."""

    model_config = ConfigDict(frozen=False)

    ok: bool = True
    changed: bool = False
    dry_run: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    state_delta: StateDelta = Field(default_factory=StateDelta)
    human_gate_required: bool = False
    rollback_token: str | None = None
    tool_name: str = ""
    call_id: str = Field(default_factory=lambda: str(uuid4()))
    duration_ms: float | None = None
    kicad_version: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, tool_name: str, *, changed: bool = True, **kwargs: object) -> ToolResult:
        """Create a successful result."""
        return cls(ok=True, changed=changed, tool_name=tool_name, **kwargs)

    @classmethod
    def failure(cls, tool_name: str, error: str, **kwargs: object) -> ToolResult:
        """Create a failed result."""
        return cls(ok=False, changed=False, tool_name=tool_name, errors=[error], **kwargs)

    @classmethod
    def dry_run_result(cls, tool_name: str, summary: str, **kwargs: object) -> ToolResult:
        """Create a dry-run result that records the simulated action."""
        return cls(
            ok=True,
            changed=False,
            dry_run=True,
            tool_name=tool_name,
            state_delta=StateDelta(summary=f"[DRY-RUN] {summary}"),
            **kwargs,
        )

    def add_warning(self, msg: str) -> None:
        """Append a non-fatal warning."""
        self.warnings.append(msg)

    def add_error(self, msg: str) -> None:
        """Append an error and mark the result as failed."""
        self.errors.append(msg)
        self.ok = False

    def to_mcp_text(self) -> str:
        """Serialize to human-readable text for MCP tool response content."""
        return json.dumps(self.model_dump(exclude_none=True), indent=2, default=str)
