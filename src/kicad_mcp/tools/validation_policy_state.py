"""Thin FastMCP adapter for validation policy state."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from mcp.server.fastmcp import FastMCP

from .metadata import headless_compatible


class ValidationPolicyState(Protocol):
    def list_drc_exclusions(self) -> str: ...
    def add_drc_exclusions(self, reason: str = "Reviewed — not actionable.") -> str: ...
    def remove_drc_exclusion(self, uuid: str) -> str: ...
    def validate_drc_exclusions(self) -> str: ...
    def list_erc_rules(self) -> str: ...
    def set_erc_rule_severity(self, rule_name: str, severity: str) -> str: ...
    def reset_erc_rules(self, rule_name: str | None = None) -> str: ...


@dataclass(frozen=True)
class ValidationPolicyStateDependencies:
    service: ValidationPolicyState


def register(mcp: FastMCP, dependencies: ValidationPolicyStateDependencies) -> None:
    """Register project-local validation policy tools."""
    service = dependencies.service

    @mcp.tool()
    @headless_compatible
    def drc_list_exclusions() -> str:
        """List all DRC violation exclusions stored for the active project.

        Returns a JSON array of exclusions, each with a 'uuid' (violation
        identifier), 'reason', and 'created' timestamp.
        """
        return service.list_drc_exclusions()

    @mcp.tool()
    @headless_compatible
    def drc_add_exclusion(reason: str = "Reviewed — not actionable.") -> str:
        """Add DRC exclusions for the current violation set.

        Runs DRC, lists all violations, and asks the user to pick which UUIDs
        to exclude.  Because MCP tools cannot interactively prompt, this tool
        excludes ALL current DRC violations and records a reason string.

        Use ``drc_list_exclusions`` afterward to review what was excluded.
        """
        return service.add_drc_exclusions(reason)

    @mcp.tool()
    @headless_compatible
    def drc_remove_exclusion(uuid: str) -> str:
        """Remove a single DRC exclusion by its violation UUID.

        Use ``drc_list_exclusions`` to retrieve the UUID of the exclusion to remove.
        """
        return service.remove_drc_exclusion(uuid)

    @mcp.tool()
    @headless_compatible
    def drc_validate_exclusions() -> str:
        """Validate that stored DRC exclusions still cover active violations.

        Re-runs DRC and reports which previously excluded violations are
        still present (valid) and which have been resolved (stale).
        """
        return service.validate_drc_exclusions()

    @mcp.tool()
    @headless_compatible
    def erc_list_rules() -> str:
        """List known ERC rules and their current severity levels.

        Severity levels are: ``error``, ``warning``, or ``ignore``.
        """
        return service.list_erc_rules()

    @mcp.tool()
    @headless_compatible
    def erc_set_rule_severity(rule_name: str, severity: str) -> str:
        """Override the severity of an ERC rule.

        Parameters
        ----------
        rule_name : str
            Name of the ERC rule (use ``erc_list_rules`` to see available names).
        severity : str
            One of ``error``, ``warning``, or ``ignore``.
        """
        return service.set_erc_rule_severity(rule_name, severity)

    @mcp.tool()
    @headless_compatible
    def erc_reset_rules(rule_name: str | None = None) -> str:
        """Reset one or all ERC rule severities back to their default (``error``).

        Parameters
        ----------
        rule_name : str | None
            Specific rule to reset, or omit to reset all rules.
        """
        return service.reset_erc_rules(rule_name)
