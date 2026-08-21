"""Thin FastMCP adapter for selective project edit re-validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class EditRevalidationService(Protocol):
    def revalidate(
        self, baseline_spec_json: str = "", manufacturer: str = "", tier: str = ""
    ) -> str: ...


@dataclass(frozen=True)
class ProjectEditRevalidationDependencies:
    service: EditRevalidationService


def register(mcp: FastMCP, dependencies: ProjectEditRevalidationDependencies) -> None:
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def project_revalidate_after_edit(
        baseline_spec_json: str = "",
        manufacturer: str = "",
        tier: str = "",
    ) -> str:
        """Re-run only the gates an edit could have invalidated; prove the rest preserved.

        Computes the semantic intent diff (like ``project_assess_edit_impact``), then
        actually re-runs only the impacted project gates -- skipping unaffected ones -- so
        a small edit does not force a full re-validation. Impacted analysis categories that
        the sign-off gate does not cover (signal integrity, power, thermal, EMC) are listed
        with the tool to re-run for each."""
        return service.revalidate(baseline_spec_json, manufacturer, tier)
