"""Thin FastMCP adapters for PCB transaction lifecycle tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import requires_kicad_running


class TransactionLifecycleService(Protocol):
    """Minimal service contract required by the adapter."""

    def begin(self) -> str: ...

    def push(self) -> str: ...

    def drop(self) -> str: ...

    def revert(self) -> str: ...

    def status_payload(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class PcbTransactionLifecycleDependencies:
    """PCB transaction dependencies injected by the composition root."""

    service: TransactionLifecycleService


def register(mcp: FastMCP, dependencies: PcbTransactionLifecycleDependencies) -> None:
    """Register PCB transaction lifecycle tools."""
    service = dependencies.service

    @mcp.tool()
    @requires_kicad_running
    def pcb_begin_commit() -> str:
        """Begin a transaction group for atomic board modifications.

        All subsequent mutations (add, remove, update operations) will be grouped
        into a single undo step in KiCad. Call pcb_push_commit to apply or
        pcb_drop_commit to discard.

        Returns:
            Confirmation message with commit status.
        """
        return service.begin()

    @mcp.tool()
    @requires_kicad_running
    def pcb_push_commit() -> str:
        """Push (commit) the current transaction group to the board.

        All mutations since pcb_begin_commit will be applied as a single undo step.

        Returns:
            Confirmation message with commit status.
        """
        return service.push()

    @mcp.tool()
    @requires_kicad_running
    def pcb_drop_commit() -> str:
        """Drop (discard) the current transaction group without applying changes.

        All mutations since pcb_begin_commit will be discarded.

        Returns:
            Confirmation message with drop status.
        """
        return service.drop()

    @mcp.tool()
    @requires_kicad_running
    def pcb_revert() -> str:
        """Revert the board to the last saved state, discarding all unsaved changes.

        WARNING: This is a destructive operation. All unsaved modifications will be lost.

        Returns:
            Confirmation message with revert status.
        """
        return service.revert()

    @mcp.tool()
    def pcb_get_live_edit_state() -> str:
        """Return sanitized native-live PCB transaction state as deterministic JSON."""
        return json.dumps(service.status_payload(), sort_keys=True)
