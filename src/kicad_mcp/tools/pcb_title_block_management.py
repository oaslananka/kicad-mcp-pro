"""Thin FastMCP adapter for PCB title-block management."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import requires_kicad_running


class TitleBlockService(Protocol):
    """Minimal service contract required by the title-block adapter."""

    def set_title_block_info(
        self,
        title: str | None = None,
        date: str | None = None,
        revision: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
    ) -> str: ...


@dataclass(frozen=True)
class PcbTitleBlockDependencies:
    """PCB title-block dependencies injected by the composition root."""

    service: TitleBlockService


def register(mcp: FastMCP, dependencies: PcbTitleBlockDependencies) -> None:
    """Register PCB title-block management tools."""
    service = dependencies.service

    @mcp.tool()
    @requires_kicad_running
    def pcb_set_title_block_info(
        title: str | None = None,
        date: str | None = None,
        revision: str | None = None,
        company: str | None = None,
        comment1: str | None = None,
        comment2: str | None = None,
        comment3: str | None = None,
        comment4: str | None = None,
    ) -> str:
        """Set board title block information (KiCad 10.0.1+).

        Title block fields appear on printed outputs and drawings.

        Args:
            title: Board title.
            date: Board date.
            revision: Board revision.
            company: Company name.
            comment1: Custom comment field 1.
            comment2: Custom comment field 2.
            comment3: Custom comment field 3.
            comment4: Custom comment field 4.

        Returns:
            Confirmation message with updated fields.
        """
        return service.set_title_block_info(
            title=title,
            date=date,
            revision=revision,
            company=company,
            comment1=comment1,
            comment2=comment2,
            comment3=comment3,
            comment4=comment4,
        )
