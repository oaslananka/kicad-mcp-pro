"""Shared validation gate data structures."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

GateStatus = Literal["PASS", "FAIL", "BLOCKED", "EMPTY", "WARN"]


@dataclass(slots=True)
class GateOutcome:
    """Structured status for a validation gate."""

    name: str
    status: GateStatus
    summary: str
    details: list[str] = field(default_factory=list)


class GateOutcomeLike(Protocol):
    """Read-only gate outcome consumed by project domain services."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def details(self) -> list[str]: ...


def combined_status(outcomes: Iterable[GateOutcomeLike]) -> GateStatus:
    """Combine gate outcomes using the established blocking-status precedence."""
    statuses = {outcome.status for outcome in outcomes}
    if "EMPTY" in statuses:
        return "EMPTY"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"
